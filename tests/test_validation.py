"""Step 7 tests: schema + business rules from the rule book catch exactly the planted rule-breakers."""

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from insightflow.cleaning import clean
from insightflow.config import load_dataset_config
from insightflow.ingestion import SOURCE_ROW, read_file
from insightflow.normalization import normalize
from insightflow.validation import validate

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
IN = load_dataset_config("SALES_002")
US = load_dataset_config("SALES_001")

GOOD = {"Order_ID": "O1", "Order_Date": "05/03/2025", "Customer_ID": "C1", "Product": "Pen Set",
        "Category": "Office Supplies", "Region": "North", "Quantity": "2", "Unit_Price": "100",
        "Sales": "180", "Discount": "0.1", "Profit": "20"}


def checked(cfg=IN, **change):
    row = dict(GOOD, **change)
    if cfg is US:
        row.update(Order_Date=change.get("Order_Date", "03/05/2015"), Region=change.get("Region", "West"),
                   Category=change.get("Category", "Technology"))
    df = pd.DataFrame([row], dtype="string")
    df.insert(0, SOURCE_ROW, [2])
    c = clean(normalize(df, cfg), cfg)
    return validate(c.data, cfg)


def checks(v):
    return {f["check"] for f in v.failures}


def test_good_row_passes():
    v = checked()
    assert v.failures == [] and v.structural_errors == [] and "schema" in v.checks_run


@pytest.mark.parametrize("change, check", [
    ({"Discount": "1.5", "Sales": "-100"}, "schema:less_than_or_equal_to(0.8)"),
    ({"Category": "Toys"}, "schema:isin(['Electronics', 'Furniture', 'Office Supplies'])"),
    ({"Quantity": "-999"}, "rule:return_sign_consistency"),          # negative qty but positive sales
    ({"Quantity": "0", "Sales": "0"}, "rule:quantity_not_zero"),
    ({"Order_Date": "19/02/2035"}, "rule:order_date_in_range"),
    ({"Sales": "500"}, "rule:sales_formula"),                         # 2 x 100 x 0.9 = 180, not 500
])
def test_rule_breakers_detected(change, check):
    assert check in checks(checked(**change))


def test_severities():
    v = checked(Sales="500")
    assert v.flagged_rows == {2} and v.quarantine_rows == set()       # formula mismatch is only flagged
    v = checked(Order_Date="19/02/2035")
    assert v.quarantine_rows == {2}


def test_returns_valid_in_india_invalid_in_us():
    ret = {"Quantity": "-2", "Sales": "-180", "Profit": "-20"}
    assert checked(IN, **ret).failures == []
    assert "schema:greater_than_or_equal_to(1.0)" in checks(checked(US, **ret))


def test_negative_profit_is_a_valid_loss():
    assert checked(Profit="-500").failures == []


def test_missing_required_column_is_structural():
    df = pd.DataFrame({SOURCE_ROW: [2], "Quantity": pd.array([1], dtype="Int64")})
    v = validate(df, IN)
    assert any("required column(s) missing" in e for e in v.structural_errors)


def test_disabled_rule_is_skipped():
    cfg = IN.model_copy(deep=True)
    cfg.rules["sales_formula"].enabled = False
    assert checked(cfg, Sales="500").failures == []


@pytest.mark.parametrize("ds", ["SALES_002", "SALES_001"])
def test_sample_data_validation_matches_answer_key(ds):
    p = SAMPLE / ds / "sales_messy.csv"
    if not p.exists():
        pytest.skip(f"{ds} not built")
    cfg = load_dataset_config(ds)
    raw = read_file(p, known_headers=set(cfg.header_map()))
    key = json.loads((SAMPLE / ds / "answer_key.json").read_text(encoding="utf-8"))
    v = validate(clean(normalize(raw.data, cfg), cfg).data, cfg)
    off = raw.metadata.header_row + 1
    expected = {i["messy_row"] + off for i in key["planted_issues"]
                if i["issue_type"] in ("date_out_of_range", "invalid_quantity", "invalid_discount")}
    assert v.quarantine_rows == expected
    assert v.structural_errors == []


def test_core_code_has_no_domain_column_names():
    """Principle: sales names live in configs/, never in the engine."""
    names = set(IN.columns)
    pattern = re.compile(r"""["'](%s)["']""" % "|".join(names))
    offenders = []
    for f in (ROOT / "src" / "insightflow").rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{f.name}:{n}: {line.strip()}")
    assert offenders == []
