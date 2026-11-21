"""Gap 4: files bigger than RAM, processed in pieces with DuckDB. Must give the SAME answer as in-memory."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from insightflow.config import CONFIG_DIR
from insightflow.pipeline import run_phase1

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"
HEADER = "Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit"
ROW = "IN-{i},05/03/2025,C1,{p},Office Supplies,North,2,100,180,0.1,20"
PRODUCTS = ["Pen Set", "Stapler", "Paper Ream", "Notebook Pack", "Desk Organizer"]


def config_copy(tmp_path, dataset="SALES_002", **policies):
    d = tmp_path / f"cfg_{len(list(tmp_path.glob('cfg_*')))}"
    shutil.copytree(CONFIG_DIR, d)
    f = d / "datasets" / f"{dataset}.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    data.setdefault("policies", {}).update(policies)
    f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return d


def outputs(res):
    p = res["output_paths"]
    clean = pd.read_csv(p["cleaned"], encoding="utf-8-sig", dtype=str, keep_default_na=False)
    quar = pd.read_csv(p["quarantine"], encoding="utf-8-sig", dtype=str, keep_default_na=False)
    dups = pd.read_csv(p["duplicates"], encoding="utf-8-sig", dtype=str, keep_default_na=False)
    return clean, quar, dups


def as_numbers(df):
    out = df.copy()
    for c in out.columns:
        num = pd.to_numeric(out[c].replace("", None), errors="coerce")
        if num.notna().sum() == (out[c] != "").sum() and (out[c] != "").any():
            out[c] = num.round(6)
    return out


def assert_same_result(a, b):
    for k in ["rows_input", "rows_output", "rows_quarantined", "rows_duplicates_removed", "rows_flagged"]:
        assert a[k] == b[k], k
    ca, qa, da = outputs(a)
    cb, qb, db = outputs(b)
    pd.testing.assert_frame_equal(as_numbers(ca), as_numbers(cb[ca.columns]), check_dtype=False)
    assert sorted(qa["source_row"]) == sorted(qb["source_row"])
    assert dict(zip(qa["source_row"], qa["_reasons"])) == dict(zip(qb["source_row"], qb["_reasons"]))
    assert sorted(zip(da["source_row"], da["duplicate_of"])) == sorted(zip(db["source_row"], db["duplicate_of"]))


@pytest.mark.parametrize("ds, chunk", [("SALES_002", 150), ("SALES_001", 1500)])
def test_chunked_equals_in_memory_on_sample_data(tmp_path, ds, chunk):
    src = SAMPLE / ds / "sales_messy.csv"
    if not src.exists():
        pytest.skip(f"{ds} not built")
    normal = run_phase1(src, ds, data_root=tmp_path / "mem")
    chunked = run_phase1(src, ds, data_root=tmp_path / "chunk",
                         config_dir=config_copy(tmp_path, ds, large_files="always", chunk_rows=chunk))
    assert normal["processing_mode"] == "in_memory" and chunked["processing_mode"] == "chunked"
    assert_same_result(normal, chunked)


def test_duplicates_far_apart_in_different_pieces(tmp_path):
    rows = [ROW.format(i=i, p=PRODUCTS[i % 5]) for i in range(1, 501)]
    rows.append(rows[3])                                   # copy of row 4, 497 rows later (another piece)
    rows.append(rows[10].replace("North", " north "))      # hidden duplicate, also far away
    p = tmp_path / "far.csv"
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "d",
                     config_dir=config_copy(tmp_path, large_files="always", chunk_rows=100))
    _, _, dups = outputs(res)
    assert res["rows_duplicates_removed"] == 2
    assert sorted(zip(dups["source_row"], dups["duplicate_of"])) == [("502", "5"), ("503", "12")]


def test_auto_switch_when_file_is_too_big(tmp_path):
    rows = [ROW.format(i=i, p=PRODUCTS[i % 5]) for i in range(1, 2001)]
    p = tmp_path / "big.csv"
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "d",
                     config_dir=config_copy(tmp_path, max_file_mb=0.01, chunk_rows=500))
    assert res["processing_mode"] == "chunked" and res["rows_output"] == 2000
    assert any("switched to chunked mode" in n for n in res["notes"])          # information, not a warning
    never = run_phase1(p, "SALES_002", data_root=tmp_path / "d2",
                       config_dir=config_copy(tmp_path, max_file_mb=0.01, large_files="never"))
    assert never["status"] == "failed" and never["error"]["code"] == "too_large"


def test_chunked_jsonl_and_parquet(tmp_path):
    src = pd.read_csv(SAMPLE / "SALES_002" / "sales_messy.csv", sep=";", encoding="utf-8-sig", dtype=str,
                      keep_default_na=False)
    jl = tmp_path / "s.jsonl"
    jl.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in src.to_dict(orient="records")) + "\n",
                  encoding="utf-8")
    pq = tmp_path / "s.parquet"
    src.to_parquet(pq, index=False)
    for f in (jl, pq):
        normal = run_phase1(f, "SALES_002", data_root=tmp_path / f"m_{f.suffix}")
        chunked = run_phase1(f, "SALES_002", data_root=tmp_path / f"c_{f.suffix}",
                             config_dir=config_copy(tmp_path, large_files="always", chunk_rows=200))
        assert_same_result(normal, chunked)


def test_chunked_ragged_rows_quarantined(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text(HEADER + "\n" + ROW.format(i=1, p="Pen Set") + "\nIN-9,oops\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "d",
                     config_dir=config_copy(tmp_path, large_files="always", chunk_rows=100))
    _, q, _ = outputs(res)
    assert res["rows_input"] == 2 and q.loc[0, "_reasons"].startswith("unreadable_row")


def test_excel_too_big_is_refused_with_advice(tmp_path):
    src = SAMPLE / "SALES_002" / "sales_messy.xlsx"
    res = run_phase1(src, "SALES_002", data_root=tmp_path / "d",
                     config_dir=config_copy(tmp_path, max_file_mb=0.01))
    assert res["status"] == "failed" and res["error"]["code"] == "too_large"


def test_chunked_fills_from_groups_across_pieces(tmp_path):
    """BR-3 in chunked mode: a blank customer in one piece is filled from the same order in another piece."""
    rows = [ROW.format(i=i, p=PRODUCTS[i % 5]).replace(",C1,", f",C{i},") for i in range(1, 301)]
    rows.append(ROW.format(i=7, p="Laptop").replace(",C1,", ",NA,").replace("Office Supplies", "Electronics"))
    p = tmp_path / "g.csv"
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "d",
                     config_dir=config_copy(tmp_path, large_files="always", chunk_rows=100))
    clean, _, _ = outputs(res)
    assert clean.loc[clean["source_row"] == "302", "Customer_ID"].tolist() == ["C7"]   # from row 8, 3 pieces earlier
    assert res["rows_flagged"] == 0


def test_chunked_falls_back_for_whole_table_policies(tmp_path):
    d = config_copy(tmp_path, large_files="always", chunk_rows=100)
    f = d / "domains" / "sales.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    data["columns"]["Profit"].update(missing_policy="impute", impute_method="median")
    f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    p = tmp_path / "s.csv"
    p.write_text(HEADER + "\n" + ROW.format(i=1, p="Pen Set").replace(",20", ",") + "\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "d", config_dir=d)
    assert any("can't use impute" in w for w in res["warnings"]) and res["rows_flagged"] == 1
