"""Missing-value choices (user request 2026-11-22): fill down / fill up, the BR-9 money guard, and the
business switches that must agree with the column limits."""

import pandas as pd
import pytest
from pydantic import ValidationError

from insightflow.cleaning import clean
from insightflow.config import ColumnSpec, DatasetConfig, load_dataset_config
from insightflow.ingestion import SOURCE_ROW
from insightflow.normalization import normalize

from test_edge_cleaning import cleaned, table, with_policy


def _rows(regions, states=None):
    return [{"Region": r, **({"State": s} if states else {})} for r, s in zip(regions, states or regions)]


# ---------------- fill down / fill up
def test_fill_down_copies_the_value_above_and_logs_the_source_row():
    c = cleaned(_rows(["North", "NA", "NA", "South", "NA"]), with_policy("Region", group_by=[], missing_policy="fill_down"))
    assert c.data["Region"].tolist() == ["North", "North", "North", "South", "South"]
    a = [x for x in c.actions if x["rule"] == "fill_down"]
    assert len(a) == 3 and "copied from row 2 (above)" in a[0]["detail"]
    assert sum(f["flag"] == "estimated_value" for f in c.flags) == 3


def test_fill_up_copies_the_value_below():
    c = cleaned(_rows(["NA", "North", "NA", "South"]), with_policy("Region", group_by=[], missing_policy="fill_up"))
    assert c.data["Region"].tolist() == ["North", "North", "South", "South"]
    assert "(below)" in c.actions[0]["detail"]


def test_nothing_to_copy_keeps_blank_and_flags():
    c = cleaned(_rows(["NA", "North"]), with_policy("Region", group_by=[], missing_policy="fill_down"))
    assert pd.isna(c.data["Region"].iloc[0])
    assert any(f["flag"] == "missing_value" and "no value to copy" in f["detail"] for f in c.flags)


def test_not_nullable_column_with_nothing_to_copy_is_set_aside():
    c = cleaned(_rows(["NA", "North"]), with_policy("Region", group_by=[], missing_policy="fill_down", nullable=False))
    assert "missing_required:Region" in c.quarantine.iloc[0]["_reasons"]


def test_fill_limit():
    cfg = with_policy("Region", group_by=[], missing_policy="fill_down", fill_limit=1)
    c = cleaned(_rows(["North", "NA", "NA"]), cfg)
    assert c.data["Region"].iloc[1] == "North" and pd.isna(c.data["Region"].iloc[2])


def test_fill_down_within_a_group_never_crosses_groups():
    cfg = with_policy("Region", missing_policy="fill_down", group_by=["State"])
    c = cleaned(_rows(["North", "South", "NA", "NA"], ["Punjab", "Kerala", "Punjab", "Goa"]), cfg)
    assert c.data["Region"].iloc[2] == "North"              # from row 2, same state, skipping Kerala
    assert pd.isna(c.data["Region"].iloc[3])                # Goa: nothing above in the same state


def test_file_order_is_used_even_if_rows_are_shuffled():
    cfg = load_dataset_config("SALES_002")
    cfg.columns["Region"] = cfg.columns["Region"].model_copy(update={"missing_policy": "fill_down", "group_by": []})
    t = table(_rows(["North", "NA", "South"]))
    norm = normalize(t, cfg)
    norm.data = norm.data.iloc[[2, 1, 0]]                    # rows arrive in a different order
    c = clean(norm, cfg)
    assert c.data.set_index(SOURCE_ROW).loc[3, "Region"] == "North"


def test_other_choices_already_exist():
    """fixed value / 0 / own text, NA (keep blank), mean / median / mode."""
    assert cleaned(_rows(["NA"]), with_policy("Region", group_by=[], missing_policy="fill_value",
                                               fill_value="Unknown")).data["Region"].iloc[0] == "Unknown"
    c = cleaned([{"Discount": "NA"}], with_policy("Discount", missing_policy="fill_value", fill_value=0))
    assert c.data["Discount"].iloc[0] == 0
    c = cleaned(_rows(["NA"]), with_policy("Region", group_by=[], missing_policy="keep_and_flag"))
    assert pd.isna(c.data["Region"].iloc[0]) and c.flags[0]["flag"] == "missing_value"


# ---------------- BR-9: money is not guessed unless the rule book says so
@pytest.mark.parametrize("update", [{"missing_policy": "impute", "impute_method": "median"},
                                    {"missing_policy": "fill_down"}, {"missing_policy": "fill_up"}])
def test_estimating_money_needs_explicit_permission(update):
    base = {"name": "Profit", "type": "float", "money": True, **update}
    with pytest.raises(ValidationError, match="BR-9"):
        ColumnSpec.model_validate(base)
    assert ColumnSpec.model_validate({**base, "allow_estimates": True}).allow_estimates


def test_fixed_value_for_money_is_allowed():
    ColumnSpec.model_validate({"name": "Profit", "type": "float", "money": True,
                               "missing_policy": "fill_value", "fill_value": 0})


def test_fill_limit_only_for_fill_down_up():
    with pytest.raises(ValidationError, match="fill_limit only applies"):
        ColumnSpec.model_validate({"name": "x", "type": "string", "fill_limit": 2})


# ---------------- business switches must agree with the column limits
def _with(cfg, **changes):
    data = cfg.model_dump()
    for path, value in changes.items():
        *keys, last = path.split("__")
        d = data
        for k in keys:
            d = d[k]
        d[last] = value
    return DatasetConfig.model_validate(data)


@pytest.mark.parametrize("ds", ["SALES_001", "SALES_002", "SALES_003"])
def test_shipped_rule_books_agree(ds):
    cfg = load_dataset_config(ds)
    assert cfg.business.returns_column == "Quantity" and cfg.business.profit_column == "Profit"


def test_returns_switch_disagreeing_with_quantity_limit_is_refused():
    cfg = load_dataset_config("SALES_002")                  # returns allowed, Quantity min -1000
    with pytest.raises(ValidationError, match="returns_allowed is false but Quantity min is -1000"):
        _with(cfg, business__returns_allowed=False)
    us = load_dataset_config("SALES_001")                   # no returns, Quantity min 1
    with pytest.raises(ValidationError, match="returns_allowed is true but Quantity min is 1"):
        _with(us, business__returns_allowed=True)


def test_profit_switch_disagreeing_is_refused():
    cfg = load_dataset_config("SALES_002")
    with pytest.raises(ValidationError, match="negative_profit_allowed is false"):
        _with(cfg, business__negative_profit_allowed=False)
    _with(cfg, business__negative_profit_allowed=False, columns__Profit__min=0)   # agrees: accepted


def test_switch_naming_unknown_column_is_refused():
    with pytest.raises(ValidationError, match="unknown column"):
        _with(load_dataset_config("SALES_002"), business__returns_column="Qty_typo")
