"""Gap 2: dated currency conversion with ECB reference rates (CurrencyConverter, offline)."""

from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from insightflow.config import load_dataset_config
from insightflow.ingestion import SOURCE_ROW
from insightflow.normalization import NotConvertible, normalize
from insightflow.normalization.currency import Rates
from insightflow.pipeline import run_phase1

IN = load_dataset_config("SALES_002")
HEADER = "Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit"
ROW = "IN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,180,0.1,20"


def converting(**currency):
    c = IN.model_copy(deep=True)
    c.currency = c.currency.model_copy(update={"rate_date_column": "Order_Date", **currency})
    return c


# ---------------- the rates themselves
def test_ecb_rate_and_weekend_fallback():
    r = Rates(max_age_days=7)
    friday, fday = r.rate("USD", "INR", date(2025, 3, 7))
    saturday, sday = r.rate("USD", "INR", date(2025, 3, 8))
    assert 80 < friday < 95 and saturday == friday and sday == fday == date(2025, 3, 7)


def test_rates_refuse_rather_than_guess():
    with pytest.raises(NotConvertible) as e:
        Rates().rate("AED", "INR", date(2025, 3, 5))             # the ECB publishes no AED rate
    assert e.value.reason == "no_exchange_rate"
    with pytest.raises(NotConvertible) as e:
        Rates().rate("USD", "INR", date(2030, 1, 1))             # beyond the bundled data
    assert e.value.reason == "rate_not_published_yet"
    with pytest.raises(NotConvertible) as e:
        Rates(max_age_days=0).rate("USD", "INR", date(2025, 3, 8))   # Saturday, no fallback allowed
    assert e.value.reason == "rate_too_old"


# ---------------- foreign amounts inside an INR dataset
def frame(values, dates):
    df = pd.DataFrame({"Sales": values, "Order_Date": dates}, dtype="string")
    df.insert(0, SOURCE_ROW, range(2, 2 + len(values)))
    return df


def test_foreign_amount_converted_at_the_row_date():
    n = normalize(frame(["US$100", "€50", "₹500"], ["05/03/2025", "05/03/2025", "05/03/2025"]),
                  converting(foreign_amounts="convert"))
    usd, _ = Rates().rate("USD", "INR", date(2025, 3, 5))
    eur, _ = Rates().rate("EUR", "INR", date(2025, 3, 5))
    assert n.data["Sales"].tolist() == [pytest.approx(100 * usd, abs=1e-3), pytest.approx(50 * eur, abs=1e-3), 500]
    logged = [c for c in n.changes if c["rule"] == "currency_converted"]
    assert len(logged) == 2 and "ECB rate of 2025-03-05" in logged[0]["detail"]


def test_conversion_stays_off_by_default():
    n = normalize(frame(["US$100"], ["05/03/2025"]), IN)
    assert pd.isna(n.data["Sales"].iloc[0]) and n.issues[0]["reason"] == "currency_mismatch"


@pytest.mark.parametrize("value, date_text, reason", [
    ("$100", "05/03/2025", "currency_mismatch"),        # bare $: which dollar? still refused
    ("AED 10", "05/03/2025", "no_exchange_rate"),
    ("US$100", "", "conversion_needs_date"),
    ("US$5%", "05/03/2025", "percent_not_allowed"),
])
def test_unconvertible_foreign_amounts(value, date_text, reason):
    n = normalize(frame([value], [date_text]), converting(foreign_amounts="convert"))
    assert pd.isna(n.data["Sales"].iloc[0]) and n.issues[0]["reason"] == reason


def test_only_money_columns_are_converted():
    cfg = converting(foreign_amounts="convert")
    df = frame(["100"], ["05/03/2025"])
    df["Quantity"] = pd.array(["US$2"], dtype="string")      # quantity is not money
    n = normalize(df, cfg)
    assert n.issues[0]["column"] == "Quantity" and n.issues[0]["reason"] == "currency_mismatch"


# ---------------- reporting currency columns
def test_reporting_currency_columns_in_pipeline(tmp_path):
    cfg_dir = tmp_path / "configs"
    import shutil
    shutil.copytree(load_dataset_config.__globals__["CONFIG_DIR"], cfg_dir)
    ds = cfg_dir / "datasets" / "SALES_002.yaml"
    ds.write_text(ds.read_text(encoding="utf-8") +
                  "\ncurrency:\n  reporting_currency: USD\n  rate_date_column: Order_Date\n", encoding="utf-8")
    p = tmp_path / "s.csv"
    p.write_text(HEADER + "\n" + ROW + "\n" + ROW.replace("IN-1", "IN-2").replace("05/03/2025", "08/03/2025") + "\n",
                 encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "data", config_dir=cfg_dir)
    out = pd.read_csv(res["output_paths"]["cleaned"], encoding="utf-8-sig")
    rate, _ = Rates().rate("INR", "USD", date(2025, 3, 5))
    assert {"Sales_USD", "Profit_USD", "Unit_Price_USD"} <= set(out.columns)
    assert out["Sales"].tolist() == [180, 180]                                     # originals unchanged
    assert out.loc[0, "Sales_USD"] == pytest.approx(180 * rate, abs=1e-3)
    assert out.loc[1, "Sales_USD"] == pytest.approx(180 * Rates().rate("INR", "USD", date(2025, 3, 7))[0], abs=1e-3)


# ---------------- config checks
@pytest.mark.parametrize("update, msg", [
    ({"foreign_amounts": "convert", "rate_date_column": None}, "rate_date_column"),
    ({"reporting_currency": "USD", "rate_date_column": "Region"}, "rate_date_column"),
    ({"reporting_currency": "usd", "rate_date_column": "Order_Date"}, "3-letter ISO"),
])
def test_bad_currency_config(update, msg):
    data = IN.model_dump()
    data["currency"].update(update)
    with pytest.raises(ValidationError, match=msg):
        type(IN).model_validate(data)
