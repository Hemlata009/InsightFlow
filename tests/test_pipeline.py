"""Steps 8–9 acceptance tests: the full pipeline turns the messy files back into the truth."""

import json
from pathlib import Path

import pandas as pd
import pytest

from insightflow.ingestion import file_sha256
from insightflow.pipeline import describe, run_phase1

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
CORE_TEXT = ["Order_ID", "Customer_ID", "Product", "Category", "Region", "Sub_Category", "Segment", "State"]
CORE_NUM = ["Quantity", "Unit_Price", "Sales", "Discount", "Profit"]


def sample(ds, name="sales_messy.csv"):
    p = SAMPLE / ds / name
    if not p.exists():
        pytest.skip(f"{ds} not built")
    return p


def answer_key(ds):
    return json.loads((SAMPLE / ds / "answer_key.json").read_text(encoding="utf-8"))


def messy_to_truth_ids(key) -> dict[int, int]:
    """messy_row -> source_row_id of the truth row (duplicate copies point at their original)."""
    dup_rows = {i["messy_row"] for i in key["planted_issues"] if i["column"] is None}
    mapping, truth_id = {}, 0
    for m in range(key["rows"]["messy"]):
        if m in dup_rows:
            mapping[m] = mapping[m - 1]
        else:
            truth_id += 1
            mapping[m] = truth_id
    return mapping


@pytest.fixture(scope="module", params=[("SALES_002", "sales_messy.csv"), ("SALES_002", "sales_messy.xlsx"),
                                        ("SALES_001", "sales_messy.csv")])
def run(request, tmp_path_factory):
    ds, name = request.param
    src = sample(ds, name)
    root = tmp_path_factory.mktemp(f"{ds}_{Path(name).suffix[1:]}")
    before = file_sha256(src)
    res = run_phase1(src, ds, data_root=root)
    return ds, name, src, root, res, before


def test_status_and_row_accounting(run):
    ds, _, _, _, res, _ = run
    assert res["status"] == "completed_with_warnings"
    assert res["rows_output"] + res["rows_quarantined"] + res["rows_duplicates_removed"] == res["rows_input"]


def test_quarantine_is_exactly_the_planted_bad_rows(run):
    ds, name, _, root, res, _ = run
    key = answer_key(ds)
    header_row = 3 if name.endswith(".xlsx") else 1
    expected = {i["messy_row"] + header_row + 1 for i in key["planted_issues"] if i["expected_action"] == "quarantine"}
    q = pd.read_csv(res["output_paths"]["quarantine"], dtype=str)
    assert set(q["source_row"].astype(int)) == expected
    assert q["_reasons"].notna().all()


def test_duplicates_removed(run):
    ds, _, _, _, res, _ = run
    key = answer_key(ds)
    planted = sum(1 for i in key["planted_issues"] if i["expected_action"].endswith("deduplicate"))
    natural = sum(n.get("count", 0) for n in key["natural_issues"] if n["issue_type"] == "exact_duplicate")
    assert res["rows_duplicates_removed"] == planted + natural


def test_cleaned_data_equals_truth(run):
    ds, name, _, _, res, _ = run
    key = answer_key(ds)
    header_row = 3 if name.endswith(".xlsx") else 1
    to_truth = messy_to_truth_ids(key)
    truth = pd.read_csv(SAMPLE / ds / "sales_truth.csv", dtype={c: str for c in CORE_TEXT}).set_index("source_row_id")
    clean = pd.read_csv(res["output_paths"]["cleaned"], dtype={c: str for c in CORE_TEXT})
    clean["truth_id"] = (clean["source_row"] - header_row - 1).map(to_truth)
    assert clean["truth_id"].is_unique
    t = truth.loc[clean["truth_id"]].reset_index(drop=True)

    planted_null = {(to_truth[i["messy_row"]], i["column"]) for i in key["planted_issues"]
                    if i["expected_action"] == "flag_missing" and i["column"] in ("Customer_ID", "Region")}
    case_only = 0
    for col in CORE_TEXT:
        exp = t[col].str.split().str.join(" ")             # truth keeps invisible spaces; we standardize them
        got = clean[col]
        for i in got.index[got.fillna("") != exp.fillna("")]:
            if (clean.at[i, "truth_id"], col) in planted_null:
                assert pd.isna(got[i])
                continue
            assert str(got[i]).casefold() == str(exp[i]).casefold(), (col, got[i], exp[i])
            case_only += 1                                  # single-occurrence names: capitals unknowable
    assert case_only <= 5
    for col in CORE_NUM:
        assert (clean[col] - t[col]).abs().max() < 1e-3, col
    assert (clean["Order_Date"] == t["Order_Date"]).all()


def test_outputs_and_audit_files(run):
    ds, _, _, root, res, _ = run
    paths = res["output_paths"]
    for k in ["cleaned", "quarantine", "duplicates", "quality_report", "cleaning_log", "metadata"]:
        assert Path(paths[k]).exists(), k
    meta = json.loads(Path(paths["metadata"]).read_text(encoding="utf-8"))
    assert meta["result"]["status"] == res["status"] and len(meta["config_sha256"]) == 64
    log = json.loads(Path(paths["cleaning_log"]).read_text(encoding="utf-8"))
    assert all({"stage", "source_row"} <= set(e) for e in log)
    assert {e["stage"] for e in log} >= {"normalize", "clean", "validate"}
    qr = json.loads(Path(paths["quality_report"]).read_text(encoding="utf-8"))
    assert qr["before"]["rows"] == res["rows_input"] and qr["after"]["rows"] == res["rows_output"]


def test_raw_file_untouched_and_copied(run):
    ds, _, src, root, res, before = run
    assert file_sha256(src) == before
    copy = Path(json.loads(Path(res["output_paths"]["metadata"]).read_text(encoding="utf-8"))["raw_copy"])
    assert copy.exists() and file_sha256(copy) == before and root in copy.parents


def test_rerun_is_idempotent_on_cleaned_output(run, tmp_path):
    ds, _, _, _, res, _ = run
    again = run_phase1(res["output_paths"]["cleaned"], ds, data_root=tmp_path)
    assert again["rows_quarantined"] == 0 and again["rows_duplicates_removed"] == 0
    assert again["rows_output"] == res["rows_output"]
    a = pd.read_csv(res["output_paths"]["cleaned"]).drop(columns="source_row")
    b = pd.read_csv(again["output_paths"]["cleaned"]).drop(columns=["source_row"])
    b = b[[c for c in a.columns]]
    pd.testing.assert_frame_equal(a, b)


def test_same_file_twice_is_noticed(tmp_path):
    src = sample("SALES_002")
    run_phase1(src, "SALES_002", data_root=tmp_path)
    second = run_phase1(src, "SALES_002", data_root=tmp_path)
    assert any("processed before" in w for w in second["warnings"])


# ---------------------------------------------------------------- statuses on small files
GOOD_ROW = "IN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,180,0.1,20"
HEADER = "Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit"


def test_clean_file_completes(tmp_path):
    p = tmp_path / "ok.csv"
    p.write_text(HEADER + "\n" + GOOD_ROW + "\n" + GOOD_ROW.replace("Pen Set", "Stapler") + "\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "data")
    assert res["status"] == "completed", describe(res)


def test_mostly_bad_file_needs_review(tmp_path):
    p = tmp_path / "bad.csv"
    rows = [GOOD_ROW] + [GOOD_ROW.replace("IN-1", f"IN-{i}").replace(",100,", ",abc,") for i in range(2, 6)]
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "data")
    assert res["status"] == "needs_review" and res["rows_quarantined"] == 4


def test_missing_required_column_fails(tmp_path):
    p = tmp_path / "nocol.csv"
    p.write_text("Order_ID,Quantity\nA,1\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "data")
    assert res["status"] == "failed" and res["error"]["code"] == "missing_required_columns"
    assert Path(res["output_paths"]["metadata"]).exists()


def test_unreadable_file_fails_with_code(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_bytes(b"")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "data")
    assert res["status"] == "failed" and res["error"]["code"] == "empty_file"


def test_ragged_rows_end_up_in_quarantine(tmp_path):
    p = tmp_path / "ragged.csv"
    p.write_text(HEADER + "\n" + GOOD_ROW + "\nIN-9,oops\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "data")
    q = pd.read_csv(res["output_paths"]["quarantine"], dtype=str)
    assert res["rows_input"] == 2 and q.loc[0, "_reasons"].startswith("unreadable_row")


def test_result_shape_is_stable(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_bytes(b"")
    failed = run_phase1(p, "SALES_002", data_root=tmp_path / "data")
    ok = run_phase1(sample("SALES_002"), "SALES_002", data_root=tmp_path / "d2")
    assert set(failed) == set(ok)
