"""Milestone 1 tests: the sample datasets are correct, traceable and reproducible."""

import json
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from scripts.fetch_superstore import TARGET, sha256_of
from scripts.sample_data import india
from scripts.sample_data.common import group_indian, with_magnitude

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"
DATASETS = ["SALES_002", pytest.param("SALES_001", marks=pytest.mark.skipif(
    not (SAMPLE / "SALES_001" / "answer_key.json").exists(),
    reason="Superstore not fetched/built (run scripts.fetch_superstore, then scripts.sample_data)"))]


def load(ds):
    d = SAMPLE / ds
    key = json.loads((d / "answer_key.json").read_text(encoding="utf-8"))
    truth = pd.read_csv(d / "sales_truth.csv", dtype={"Customer_ID": str, "Order_ID": str})
    f = key["files"]["messy_csv"]
    messy = pd.read_csv(d / f["name"], encoding=f["encoding"], sep=f["delimiter"], dtype=str,
                        keep_default_na=False)
    return key, truth, messy


# ---------- formatting helpers ----------
@pytest.mark.parametrize("value, text", [
    (100000, "1,00,000.00"), (1234567.5, "12,34,567.50"), (999, "999.00"), (-250000, "-2,50,000.00")])
def test_indian_grouping(value, text):
    assert group_indian(value) == text


@pytest.mark.parametrize("value, grouping, text", [
    (1534.2, "international", "1.5342K"), (2500000, "international", "2.5M"),
    (123456.78, "indian", "1.2345678 L"), (25000000, "indian", "2.5 Cr"), (4500, "indian", "4.5K")])
def test_magnitude_text_is_exact(value, grouping, text):
    assert with_magnitude(value, grouping) == text


# ---------- truth data follows business rules ----------
@pytest.mark.parametrize("ds", DATASETS)
def test_truth_business_rules(ds):
    _, t, _ = load(ds)
    expected = t["Quantity"] * t["Unit_Price"] * (1 - t["Discount"])
    assert (abs(expected - t["Sales"]) <= 0.01 + 1e-6 * abs(t["Sales"])).all()
    assert t["Discount"].between(0, 0.8).all()
    assert t["source_row_id"].is_unique
    assert t[["Order_ID", "Order_Date", "Customer_ID", "Product", "Region"]].notna().all().all()
    assert ((t["Quantity"] < 0) == (t["Sales"] < 0)).all()     # returns are consistent


# ---------- every planted issue really exists ----------
@pytest.mark.parametrize("ds", DATASETS)
def test_answer_key_matches_files(ds):
    key, truth, messy = load(ds)
    canon = {v: k for k, v in key["column_mapping"].items()}   # canonical -> messy header
    truth = truth.set_index("source_row_id")
    assert len(messy) == key["rows"]["messy"]
    assert key["planted_issues"], "no issues planted"
    for iss in key["planted_issues"]:
        if iss["column"] is None:   # duplicates
            continue
        cell = messy.iloc[iss["messy_row"]][canon[iss["column"]]]
        assert cell == iss["messy_value"], iss["issue_id"]
        true = truth.loc[iss["source_row_id"], iss["column"]]
        exp = iss["expected_value"]
        assert (abs(true - exp) < 1e-9) if isinstance(exp, float) else str(true) == str(exp), iss["issue_id"]


@pytest.mark.parametrize("ds", DATASETS)
def test_duplicates_point_at_a_copy(ds):
    key, _, messy = load(ds)
    canon = {v: k for k, v in key["column_mapping"].items()}
    oid = canon["Order_ID"]
    for iss in key["planted_issues"]:
        if iss["issue_type"] in ("exact_duplicate", "hidden_duplicate"):
            r = iss["messy_row"]
            assert messy.iloc[r][oid] == messy.iloc[r - 1][oid]
            if iss["issue_type"] == "exact_duplicate":
                assert messy.iloc[r].equals(messy.iloc[r - 1])


@pytest.mark.parametrize("ds", DATASETS)
def test_excel_header_on_row_3(ds):
    key, _, messy = load(ds)
    wb = openpyxl.load_workbook(SAMPLE / ds / "sales_messy.xlsx", read_only=True)
    assert wb.sheetnames == ["Notes", "Sales"]
    header = [c.value for c in next(wb["Sales"].iter_rows(min_row=3, max_row=3))]
    assert header == list(messy.columns)
    wb.close()


# ---------- reproducible ----------
def test_india_rebuild_is_identical(tmp_path):
    india.build(tmp_path)
    for name in ["sales_truth.csv", "sales_messy.csv", "answer_key.json"]:
        assert (tmp_path / name).read_bytes() == (SAMPLE / "SALES_002" / name).read_bytes(), name


# ---------- planted stories exist (for later phases) ----------
def test_india_festive_boost():
    _, t, _ = load("SALES_002")
    d = pd.to_datetime(t["Order_Date"])
    per_month = t.groupby(d.dt.strftime("%Y-%m")).size()   # each calendar month of each year
    is_festive = per_month.index.str[-2:].isin(["10", "11"])
    assert per_month[is_festive].mean() > per_month[~is_festive].mean() * 1.2


def test_india_planted_drop():
    _, t, _ = load("SALES_002")
    t = t[(t.Region == "North") & (t.Category == "Electronics") & (t.Quantity > 0)]
    by_month = t.groupby(pd.to_datetime(t["Order_Date"]).dt.strftime("%Y-%m"))["Sales"].sum()
    typical = by_month.drop("2026-03").median()
    assert by_month.get("2026-03", 0) < typical


# ---------- Superstore download check (no network) ----------
def test_checksum_rejects_wrong_file(tmp_path):
    from scripts.fetch_superstore import fetch
    src = tmp_path / "fake.csv"
    src.write_text("not superstore")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        fetch(target=tmp_path / "out.csv", url=src.as_uri(), expected="0" * 64)
    assert not (tmp_path / "out.csv").exists()


@pytest.mark.skipif(not TARGET.exists(), reason="Superstore not fetched")
def test_raw_superstore_unchanged():
    from scripts.fetch_superstore import SHA256
    assert sha256_of(TARGET) == SHA256
