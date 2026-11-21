"""Priority 4: every audit entry has the standard shape; plugin changes are traceable per cell."""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from insightflow.audit.log import FIELDS, KINDS, trace
from insightflow.config import CONFIG_DIR
from insightflow.pipeline import run_phase1

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def sales_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("audit")
    res = run_phase1(SAMPLE / "SALES_002" / "sales_messy.csv", "SALES_002", data_root=root)
    log = json.loads(Path(res["output_paths"]["cleaning_log"]).read_text(encoding="utf-8"))
    return res, log, root


def test_every_entry_has_the_standard_shape(sales_run):
    res, log, _ = sales_run
    assert log and all(set(e) == set(FIELDS) for e in log)
    assert [e["seq"] for e in log] == list(range(1, len(log) + 1))
    assert {e["run_id"] for e in log} == {res["run_id"]}
    assert {e["kind"] for e in log} <= set(KINDS) and all(e["rule"] for e in log)


def test_all_kinds_present_with_meaning(sales_run):
    _, log, _ = sales_run
    kinds = {e["kind"] for e in log}
    assert {"change", "issue", "rejection"} <= kinds        # (no flags left: the business rules fill every blank)
    issue = next(e for e in log if e["kind"] == "issue")
    assert issue["rule"].startswith("unconvertible:") and issue["old"] is not None and issue["severity"] == "quarantine"
    rej = next(e for e in log if e["kind"] == "rejection")
    assert rej["severity"] == "quarantine" and rej["rule"].startswith(("rule:", "schema:"))


def test_quality_report_summarizes_the_log(sales_run):
    res, log, _ = sales_run
    qr = json.loads(Path(res["output_paths"]["quality_report"]).read_text(encoding="utf-8"))
    assert qr["audit"]["entries"] == len(log) and sum(qr["audit"]["by_kind"].values()) == len(log)


def test_trace_one_row(sales_run):
    _, log, _ = sales_run
    row = next(e["source_row"] for e in log if e["rule"] == "number:magnitude_suffix")
    events = trace(log, row)
    assert events and all(e["source_row"] == row for e in events)
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)


def test_trace_command(sales_run, tmp_path):
    _, log, root = sales_run
    row = next(e["source_row"] for e in log if e["rule"] == "derived")
    code = (f"import sys; sys.argv=['x','trace','SALES_002','{row}']; "
            f"import insightflow.pipeline.phase1 as p; from pathlib import Path; p.DATA_ROOT=Path(r'{root}'); "
            "import insightflow.audit.__main__ as m; m.DATA_ROOT=p.DATA_ROOT; sys.exit(m.main())")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and f"Row {row}" in out.stdout and "derived" in out.stdout


def test_plugin_changes_logged_per_cell_with_provenance(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "plug_upper.py").write_text(textwrap.dedent("""
        from insightflow.hooks import hookimpl
        __version__ = "1.2.0"

        @hookimpl
        def after_normalize(data, cfg):
            data["Order_ID"] = data["Order_ID"].str.lower()
            return data
    """), encoding="utf-8")
    cfg_dir = tmp_path / "configs"
    shutil.copytree(CONFIG_DIR, cfg_dir)
    ds = cfg_dir / "datasets" / "SALES_002.yaml"
    ds.write_text(ds.read_text(encoding="utf-8") + "\nplugins: [plug_upper]\n", encoding="utf-8")
    src = tmp_path / "in.csv"
    src.write_text("Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit\n"
                   "IN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,180,0.1,20\n"
                   "in-2,05/03/2025,C1,Stapler,Office Supplies,North,2,100,180,0.1,20\n", encoding="utf-8")
    res = run_phase1(src, "SALES_002", data_root=tmp_path / "d", config_dir=cfg_dir)
    log = json.loads(Path(res["output_paths"]["cleaning_log"]).read_text(encoding="utf-8"))
    plug = [e for e in log if e["kind"] == "plugin_change"]
    assert plug == [{**plug[0], "source_row": 2, "column": "Order_ID", "old": "IN-1", "new": "in-1",
                     "rule": "plug_upper.after_normalize"}]                 # only the cell that really changed
    meta = json.loads(Path(res["output_paths"]["metadata"]).read_text(encoding="utf-8"))
    p = meta["plugins"][0]
    assert p["name"] == "plug_upper" and p["version"] == "1.2.0" and len(p["sha256"]) == 64
    assert p["hooks"] == ["after_normalize"]


def test_chunked_log_has_the_same_shape(tmp_path):
    import yaml
    cfg_dir = tmp_path / "configs"
    shutil.copytree(CONFIG_DIR, cfg_dir)
    f = cfg_dir / "datasets" / "SALES_002.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    data["policies"].update(large_files="always", chunk_rows=300)
    f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    res = run_phase1(SAMPLE / "SALES_002" / "sales_messy.csv", "SALES_002", data_root=tmp_path / "d", config_dir=cfg_dir)
    log = json.loads(Path(res["output_paths"]["cleaning_log"]).read_text(encoding="utf-8"))
    assert all(set(e) == set(FIELDS) for e in log)
    assert [e["seq"] for e in log] == list(range(1, len(log) + 1))
