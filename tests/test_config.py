"""Step 2 tests: the rule book loads, rejects mistakes, and agrees with the known-good truth data."""

import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from insightflow.config import CONFIG_DIR, deep_merge, load_dataset_config, normalize_header
from scripts.sample_data import india, superstore

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
HEADERS = {"SALES_001": superstore.HEADER_MAP, "SALES_002": india.HEADER_MAP}


def truth_or_skip(ds):
    p = SAMPLE / ds / "sales_truth.csv"
    if not p.exists():
        pytest.skip(f"{ds} not built")
    return pd.read_csv(p, dtype={"Customer_ID": str, "Order_ID": str})


# ---------- loading & layering ----------
@pytest.mark.parametrize("ds", ["SALES_001", "SALES_002"])
def test_dataset_config_loads(ds):
    cfg = load_dataset_config(ds)
    assert cfg.dataset_id == ds and cfg.domain == "sales"
    assert len(cfg.required_columns) == 11


def test_locales_resolved():
    assert load_dataset_config("SALES_002").locale.date_order == "DMY"
    assert load_dataset_config("SALES_001").locale.date_order == "MDY"
    assert load_dataset_config("SALES_002").locale.magnitudes["CR"] == 1e7


def test_dataset_layer_overrides_domain():
    us, india_cfg = load_dataset_config("SALES_001"), load_dataset_config("SALES_002")
    assert us.business.returns_allowed is False and us.columns["Quantity"].min == 1
    assert india_cfg.business.returns_allowed is True and india_cfg.columns["Quantity"].min == -1000
    assert india_cfg.columns["Quantity"].max == 1000          # untouched domain value survives the merge


def test_deep_merge_replaces_lists_and_merges_dicts():
    assert deep_merge({"a": {"x": 1, "y": 2}, "l": [1]}, {"a": {"y": 3}, "l": [9]}) == \
        {"a": {"x": 1, "y": 3}, "l": [9]}


# ---------- header aliases ----------
@pytest.mark.parametrize("raw, norm", [(" Unit Price (INR) ", "unit_price_inr"),
                                       ("ORDER DATE", "order_date"), ("Sub-Category", "sub_category")])
def test_normalize_header(raw, norm):
    assert normalize_header(raw) == norm


@pytest.mark.parametrize("ds", ["SALES_001", "SALES_002"])
def test_every_messy_header_maps_to_its_column(ds):
    cfg = load_dataset_config(ds)
    for canonical, messy_header in HEADERS[ds].items():
        assert cfg.canonical_name(messy_header) == canonical, messy_header


# ---------- the rule book agrees with known-good data ----------
@pytest.mark.parametrize("ds", ["SALES_001", "SALES_002"])
def test_truth_obeys_rule_book(ds):
    cfg, t = load_dataset_config(ds), truth_or_skip(ds)
    for col, spec in cfg.columns.items():
        s = t[col]
        if not spec.nullable:
            assert s.notna().all(), col
        if spec.allowed_values:
            assert set(s.dropna()) <= set(spec.allowed_values), col
        if spec.min is not None:
            assert (s >= spec.min).all(), col
        if spec.max is not None:
            assert (s <= spec.max).all(), col
    d = pd.to_datetime(t["Order_Date"]).dt.date
    assert d.min() >= cfg.date_range.min and d.max() <= cfg.date_range.max
    assert (t["Quantity"] != 0).all()
    if not cfg.business.returns_allowed:
        assert (t["Quantity"] > 0).all()


# ---------- mistakes in the rule book are rejected ----------
@pytest.fixture
def config_copy(tmp_path):
    dst = tmp_path / "configs"
    shutil.copytree(CONFIG_DIR, dst)
    return dst


def _edit(path, fn):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.mark.parametrize("change, message", [
    (lambda d: d["columns"]["Quantity"].update(type="number"), "type"),
    (lambda d: d["columns"]["Discount"].update(min=0.9), "min 0.9 > max"),
    (lambda d: d["rules"]["quantity_not_zero"]["params"].update(column="Qty"), "unknown column"),
    (lambda d: d["columns"]["Profit"].update(colour="red"), "colour"),        # typo / unknown key
    (lambda d: d["columns"]["Profit"].update(aliases=["sales"]), "maps to both"),
])
def test_bad_domain_config_rejected(config_copy, change, message):
    _edit(config_copy / "domains" / "sales.yaml", change)
    with pytest.raises(ValidationError, match=message):
        load_dataset_config("SALES_002", config_copy)


def test_unknown_locale_rejected(config_copy):
    _edit(config_copy / "datasets" / "SALES_002.yaml", lambda d: d.update(locale="xx_XX"))
    with pytest.raises(ValueError, match="unknown locale"):
        load_dataset_config("SALES_002", config_copy)


def test_missing_dataset_config():
    with pytest.raises(FileNotFoundError):
        load_dataset_config("NOPE_999")


@pytest.mark.parametrize("change, message", [
    (lambda d: d["columns"]["Order_ID"].update(missing_policy="keep_and_flag"), "conflict"),
    (lambda d: d["columns"]["Sales"].pop("derive_expression"), "needs derive_expression"),
    (lambda d: d["columns"]["Sales"].update(derive_expression="Quantity * Price"), "unknown column"),
    (lambda d: d["columns"]["Sales"].update(derive_expression="Sales * 2"), "refers to itself"),
    (lambda d: d["columns"]["Sales"].update(derive_expression="__import__('os')"), "may only use"),
    (lambda d: d["columns"]["Region"].update(allowed_values=[]), "empty"),
    (lambda d: d["columns"]["Quantity"].update(normalize_case=True), "only applies to string"),
])
def test_conflicting_rules_rejected(config_copy, change, message):
    _edit(config_copy / "domains" / "sales.yaml", change)
    with pytest.raises(ValidationError, match=message):
        load_dataset_config("SALES_002", config_copy)
