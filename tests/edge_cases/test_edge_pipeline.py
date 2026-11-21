"""Edge-case group 5: whole-pipeline cases (schema drift, formula injection, output encoding, conflicts)."""

from pathlib import Path

import pandas as pd

from insightflow.config import load_dataset_config
from insightflow.ingestion import read_file
from insightflow.pipeline import run_phase1
from insightflow.profiling import profile

HEADER = "Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit"
ROW = "IN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,180,0.1,20"


def write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_schema_drift_between_versions_is_reported(tmp_path):
    root = tmp_path / "data"
    run_phase1(write(tmp_path / "v1.csv", HEADER + "\n" + ROW + "\n"), "SALES_002", data_root=root)
    v2 = HEADER.replace("Quantity", "Qty") + ",Notes\n" + ROW + ",gift\n"        # renamed header + new column
    res = run_phase1(write(tmp_path / "v2.csv", v2), "SALES_002", data_root=root)
    sc = res["schema_changes"]
    assert sc["added"] == ["Notes"] and sc["header_spelling_changed"] == ["'Quantity' -> 'Qty'"]
    assert any("extra column(s) not in the rule book added" in n for n in res["notes"])       # Notes: unknown
    assert not any("since the last run" in w for w in res["warnings"])
    v3 = ",".join(h for h in HEADER.split(",") if h != "Profit") + "\n" + ROW.rsplit(",", 1)[0] + "\n"
    res3 = run_phase1(write(tmp_path / "v3.csv", v3), "SALES_002", data_root=root)
    assert res3["status"] == "failed" and res3["schema_changes"]["removed"] == ["Notes", "Profit"]


def test_first_run_has_no_schema_changes(tmp_path):
    res = run_phase1(write(tmp_path / "a.csv", HEADER + "\n" + ROW + "\n"), "SALES_002", data_root=tmp_path / "d")
    assert res["schema_changes"] == {}


def test_formula_like_cells_are_reported_not_numbers(tmp_path):
    # (no commas inside the formulas: an unquoted comma would split the CSV cell)
    p = write(tmp_path / "f.csv", HEADER + "\n" + ROW.replace("Pen Set", "=HYPERLINK(\"http://evil.example\")")
              + "\n" + ROW.replace("IN-1", "IN-2").replace("Pen Set", "@SUM(A1:A9)").replace(",20", ",-20") + "\n")
    cfg = load_dataset_config("SALES_002")
    rep = profile(read_file(p, known_headers=set(cfg.header_map())).data, cfg)
    cols = {c["canonical"]: c for c in rep["columns"].values()}
    assert cols["Product"]["formula_like"] == 2 and cols["Profit"]["formula_like"] == 0   # -20 is a number
    assert any("could run as formulas" in f["message"] for f in rep["findings"])


def test_outputs_open_correctly_in_excel_and_round_trip(tmp_path):
    p = write(tmp_path / "r.csv", HEADER + "\n" + ROW.replace("Pen Set", "Café ₹ ಪೆನ್") + "\n")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "d")
    out = Path(res["output_paths"]["cleaned"])
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")                                 # BOM for Excel
    assert pd.read_csv(out, encoding="utf-8-sig")["Product"].iloc[0] == "Café ₹ ಪೆನ್"
    again = run_phase1(out, "SALES_002", data_root=tmp_path / "d2")                     # our reader accepts it
    assert again["rows_output"] == 1 and again["rows_quarantined"] == 0


def test_conflicting_rules_two_reasons_for_one_row(tmp_path):
    # One row breaks two rules: both reasons are kept, the row is counted once.
    bad = ROW.replace(",2,100,180,0.1,", ",-999,100,180,1.5,")
    res = run_phase1(write(tmp_path / "c.csv", HEADER + "\n" + bad + "\n"), "SALES_002", data_root=tmp_path / "d")
    q = pd.read_csv(res["output_paths"]["quarantine"], encoding="utf-8-sig", dtype=str)
    assert res["rows_quarantined"] == 1
    assert "less_than_or_equal_to(0.8)" in q.loc[0, "_reasons"] and "return_sign_consistency" in q.loc[0, "_reasons"]


def test_rule_book_column_disappearing_is_a_warning(tmp_path):
    root = tmp_path / "data"
    with_optional = HEADER + ",Segment\n" + ROW + ",Consumer\n"
    run_phase1(write(tmp_path / "a.csv", with_optional), "SALES_002", data_root=root)
    res = run_phase1(write(tmp_path / "b.csv", HEADER + "\n" + ROW + "\n"), "SALES_002", data_root=root)
    assert any("rule-book columns removed since the last run: ['Segment']" in w for w in res["warnings"])
    assert res["status"] == "completed_with_warnings"


def test_truth_after_messy_is_completed(tmp_path):
    """The explorer case: messy file first, then the truth file (one extra unknown column) -> completed."""
    root = tmp_path / "data"
    sample = Path(__file__).resolve().parents[2] / "data" / "sample" / "SALES_002"
    run_phase1(sample / "sales_messy.csv", "SALES_002", data_root=root)
    res = run_phase1(sample / "sales_truth.csv", "SALES_002", data_root=root)
    assert res["status"] == "completed", res["warnings"]
