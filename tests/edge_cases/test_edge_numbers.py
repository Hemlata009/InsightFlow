"""Edge-case group 2: numbers, money and locales."""

import pandas as pd
import pytest
import yaml

from insightflow.config import CONFIG_DIR, LocaleSpec, load_dataset_config
from insightflow.ingestion import SOURCE_ROW
from insightflow.normalization import NotConvertible, normalize, parse_number

IN = load_dataset_config("SALES_002")
US = load_dataset_config("SALES_001")
LOCALES = yaml.safe_load((CONFIG_DIR / "locales.yaml").read_text(encoding="utf-8"))
DE = LocaleSpec.model_validate(LOCALES["de_DE"])
CA = LocaleSpec.model_validate({**LOCALES["en_US"], "description": "Canada", "currency_code": "CAD"})


def val(text, loc):
    return parse_number(text, loc)[0]


def reason(text, loc):
    with pytest.raises(NotConvertible) as e:
        parse_number(text, loc)
    return e.value.reason


# ---------------- European decimal comma
@pytest.mark.parametrize("text, value", [("1.234,56", 1234.56), ("1.234", 1234), ("12,5", 12.5), ("€ 1.000.000,00", 1e6),
                                         ("2,5 Mio", 2.5e6), ("-0,75", -0.75), ("12,5 %", 0.125)])
def test_european_locale(text, value):
    assert val(text, DE) == pytest.approx(value)


def test_same_text_means_different_numbers_by_locale():
    assert val("1.234", US.locale) == pytest.approx(1.234)      # US: decimal point
    assert val("1.234", DE) == 1234                              # Germany: thousands point
    assert reason("1,234.56", DE) == "bad_grouping"              # US style refused in a German dataset
    assert reason("1.234,56", US.locale) == "bad_grouping"


# ---------------- currency forms and ambiguity
@pytest.mark.parametrize("text, value", [("Rs. 1,500", 1500), ("Rs.1,500", 1500), ("Rs 200", 200), ("INR 5", 5),
                                         ("₨ 50", 50), ("1,00,000 INR", 100000)])
def test_indian_currency_forms(text, value):
    assert val(text, IN.locale) == value


def test_dollar_sign_belongs_to_the_dataset_currency():
    assert val("$500", US.locale) == 500                         # USD dataset
    assert val("$500", CA) == 500                                # CAD dataset: "$" is Canadian dollars
    assert reason("US$500", CA) == "currency_mismatch"           # explicit US dollars in a CAD dataset
    assert reason("C$500", US.locale) == "currency_mismatch"
    assert reason("$500", IN.locale) == "currency_mismatch"


@pytest.mark.parametrize("text", ["€40", "£40", "AUD 40", "40 GBP", "¥500", "AED 10"])
def test_foreign_currency_in_india_refused(text):
    assert reason(text, IN.locale) == "currency_mismatch"


# ---------------- signs
@pytest.mark.parametrize("text, value", [("−500", -500), ("–500", -500), ("500-", -500),
                                         ("+500", 500), ("₹-1,000", -1000), ("-₹1,000", -1000)])
def test_minus_signs(text, value):
    assert val(text, IN.locale) == value


# ---------------- size and precision
def test_huge_numbers_refused_not_rounded():
    assert reason("12345678901234567", IN.locale) == "precision_loss"
    assert val("123456789012345", IN.locale) == 123456789012345      # 15 digits: exact


def test_zero_and_scientific():
    assert val("0", IN.locale) == 0 and val("-0", IN.locale) == 0
    assert reason("1e5", IN.locale) == "not_a_number"                # parser path refuses scientific text


def test_normalizer_routes_long_numbers_to_the_safe_parser():
    df = pd.DataFrame({SOURCE_ROW: [2, 3], "Sales": ["12345678901234567", "15"]}, dtype="string")
    df[SOURCE_ROW] = [2, 3]
    n = normalize(df, IN)
    assert pd.isna(n.data.loc[0, "Sales"]) and n.data.loc[1, "Sales"] == 15
    assert n.issues[0]["reason"] == "precision_loss"


def test_normalizer_in_european_locale_does_not_misread_plain_looking_numbers():
    cfg = IN.model_copy(deep=True)
    cfg.locale = DE
    df = pd.DataFrame({"Sales": ["1.234", "1.234,5", "12"]}, dtype="string")
    n = normalize(df, cfg)
    assert list(n.data["Sales"]) == [1234, 1234.5, 12]


@pytest.mark.parametrize("text", ["(500-)", "-(500)", "--500", "-500-", "(-500)", "-₹-500"])
def test_two_minus_markers_are_refused(text):
    assert reason(text, IN.locale) == "conflicting_signs"
