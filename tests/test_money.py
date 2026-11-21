"""Priority 3: financial precision. Exact Decimal maths, lossless float storage, half-up rounding."""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from insightflow.cleaning import clean
from insightflow.config import load_dataset_config
from insightflow.ingestion import SOURCE_ROW
from insightflow.money import evaluate, exact_mean, exact_ratio, exact_sum, minor_units, quantize, to_decimal
from insightflow.normalization import normalize

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
IN = load_dataset_config("SALES_002")


def test_float_problems_we_avoid():
    total = 0.0
    for _ in range(10):                                # plain running total (how most code adds up)
        total += 0.1
    assert total != 1.0                                # float drift: 0.9999999999999999
    # (Python 3.12+'s built-in sum() compensates; pandas/numpy and loops don't promise that)
    assert round(2.675, 2) == 2.67                     # float rounding surprise
    assert exact_sum([0.1] * 10) == Decimal("1.0")
    assert quantize(Decimal("2.675"), 2) == Decimal("2.68")
    assert quantize(Decimal("-2.675"), 2) == Decimal("-2.68")


@pytest.mark.parametrize("v, d", [(__import__("numpy").float64(1.5), "1.5"), (0.1, "0.1"), (1534.2, "1534.2"), (123456.78, "123456.78"), (41.9136, "41.9136"),
                                  (-1401.97, "-1401.97"), (7, "7"), ("12.50", "12.50"), (None, None),
                                  (float("nan"), None)])
def test_to_decimal_recovers_typed_value(v, d):
    assert to_decimal(v) == (Decimal(d) if d is not None else None)


@pytest.mark.parametrize("ds", ["SALES_002", "SALES_001"])
def test_float_storage_is_lossless_for_every_money_value(ds):
    """Every money value read as float converts back to the EXACT decimal written in the file."""
    p = SAMPLE / ds / "sales_truth.csv"
    if not p.exists():
        pytest.skip(f"{ds} not built")
    text = pd.read_csv(p, dtype=str)
    num = pd.read_csv(p)
    for col in ["Unit_Price", "Sales", "Profit"]:
        for t, f in zip(text[col], num[col]):
            assert to_decimal(f) == Decimal(t), (col, t, f)
        assert exact_sum(num[col]) == sum(Decimal(t) for t in text[col])


def test_exact_helpers():
    assert quantize(exact_mean([1, 2, 2]), 10) == Decimal("1.6666666667") and exact_mean([None]) is None
    assert exact_ratio(25, 100) == Decimal("0.25") and exact_ratio(1, 0) is None
    assert minor_units("INR") == 2 and minor_units("JPY") == 0


def test_formula_evaluation_is_exact_and_safe():
    row = {"Quantity": 3, "Unit_Price": 0.1, "Discount": 0.0}
    assert evaluate("Quantity * Unit_Price * (1 - Discount)", row) == Decimal("0.3")    # float gives 0.30000000000000004
    assert evaluate("Sales / Quantity", {"Sales": 1, "Quantity": 0}) is None           # division by zero
    assert evaluate("Sales / Quantity", {"Sales": None, "Quantity": 2}) is None        # missing value
    with pytest.raises(ValueError):
        evaluate("__import__('os').system('x')", {})
    with pytest.raises(ValueError):
        evaluate("Sales ** 2", {"Sales": 2})


def test_derived_value_rounds_half_up_not_float():
    # Missing Sales = 1 x 2.675 x (1 - 0) = 2.675 -> 2.68 (float round() would give 2.67)
    df = pd.DataFrame([{"Order_ID": "O1", "Order_Date": "05/03/2025", "Customer_ID": "C1", "Product": "Pen Set",
                        "Category": "Office Supplies", "Region": "North", "Quantity": "1", "Unit_Price": "2.675",
                        "Sales": "NA", "Discount": "0", "Profit": "1"}], dtype="string")
    df.insert(0, SOURCE_ROW, [2])
    c = clean(normalize(df, IN), IN)
    assert c.data.loc[0, "Sales"] == 2.68
    assert c.actions[0]["new"] == 2.68
