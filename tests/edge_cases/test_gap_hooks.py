"""Gap 3: add-on steps via pluggy: transforms, extra checks, and the safety rules."""

import shutil
import sys
import textwrap
import uuid
from pathlib import Path

import pandas as pd
import pytest

from insightflow.config import CONFIG_DIR
from insightflow.pipeline import run_phase1

HEADER = "Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit"
ROW = "IN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,180,0.1,20"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A config copy whose SALES_002 uses the plugin module we write, and a 2-row input file."""
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg_dir = tmp_path / "configs"
    shutil.copytree(CONFIG_DIR, cfg_dir)
    src = tmp_path / "in.csv"
    src.write_text(HEADER + "\n" + ROW + "\n" + ROW.replace("IN-1", "in-2").replace(",20", ",500") + "\n",
                   encoding="utf-8")

    def make(code: str, extra_plugins=()):
        name = f"plug_{uuid.uuid4().hex[:8]}"
        (tmp_path / f"{name}.py").write_text("from insightflow.hooks import hookimpl\nfrom insightflow.ingestion "
                                             "import SOURCE_ROW\n" + textwrap.dedent(code), encoding="utf-8")
        ds = cfg_dir / "datasets" / "SALES_002.yaml"
        base = ds.read_text(encoding="utf-8").split("\nplugins:")[0]
        ds.write_text(base + f"\nplugins: [{', '.join([name, *extra_plugins])}]\n", encoding="utf-8")
        return run_phase1(src, "SALES_002", data_root=tmp_path / "data", config_dir=cfg_dir)
    return make


def test_transform_plugin_changes_values_and_is_logged(setup):
    res = setup("""
        @hookimpl
        def after_normalize(data, cfg):
            data["Order_ID"] = data["Order_ID"].str.upper()
            return data
    """)
    out = pd.read_csv(res["output_paths"]["cleaned"], encoding="utf-8-sig")
    assert out["Order_ID"].tolist() == ["IN-1", "IN-2"] and res["plugins"]
    log = pd.read_json(res["output_paths"]["cleaning_log"])
    assert (log["stage"] == "plugin").any()


def test_extra_check_plugin_flags_rows(setup):
    res = setup("""
        @hookimpl
        def extra_checks(data, cfg):
            bad = data[data["Profit"] > data["Sales"]]
            return [{"source_row": int(r[SOURCE_ROW]), "check": "profit_exceeds_sales", "column": "Profit",
                     "value": float(r["Profit"]), "severity": "flag"} for _, r in bad.iterrows()]
    """)
    assert res["rows_flagged"] == 1 and any("profit_exceeds_sales" in v for v in res["validation_errors"])


def test_plugin_may_quarantine(setup):
    res = setup("""
        @hookimpl
        def extra_checks(data, cfg):
            return [{"source_row": int(data[SOURCE_ROW].iloc[0]), "check": "blocked_customer", "severity": "quarantine"}]
    """)
    assert res["rows_quarantined"] == 1 and res["rows_output"] == 1


@pytest.mark.parametrize("code", [
    """
    @hookimpl
    def after_clean(data, cfg):
        return data.iloc[:1]                      # drops a row: not allowed
    """,
    """
    @hookimpl
    def after_ingest(data, cfg):
        raise ValueError("boom")
    """,
    """
    @hookimpl
    def extra_checks(data, cfg):
        return [{"oops": 1}]                       # malformed result
    """,
])
def test_misbehaving_plugins_fail_the_run_cleanly(setup, code):
    res = setup(code)
    assert res["status"] == "failed" and res["error"]["code"] == "plugin_error"
    assert Path(res["output_paths"]["metadata"]).exists()


def test_missing_plugin_module(setup):
    res = setup("", extra_plugins=["no_such_plugin_xyz"])
    assert res["error"]["code"] == "plugin_error" and "could not be imported" in res["error"]["message"]


def test_bundled_example_plugin(tmp_path):
    cfg_dir = tmp_path / "configs"
    shutil.copytree(CONFIG_DIR, cfg_dir)
    ds = cfg_dir / "datasets" / "SALES_002.yaml"
    ds.write_text(ds.read_text(encoding="utf-8") + "\nplugins: [plugins.sales_sanity]\n", encoding="utf-8")
    src = tmp_path / "in.csv"
    src.write_text(HEADER + "\n" + ROW.replace(",20", ",900") + "\n", encoding="utf-8")
    res = run_phase1(src, "SALES_002", data_root=tmp_path / "data", config_dir=cfg_dir)
    assert any("plugins.sales_sanity:profit_exceeds_sales" in v for v in res["validation_errors"])
    assert "plugins" in sys.modules
