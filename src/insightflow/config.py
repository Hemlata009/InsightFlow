"""Load and validate the layered rule book: default -> domain -> dataset.

    cfg = load_dataset_config("SALES_002")
    cfg.columns[name].max            # e.g. 0.8 for a discount column
    cfg.locale.date_order            # "DMY"
    cfg.header_map()                 # normalized alias -> canonical column name
"""

from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"

ColumnType = Literal["string", "integer", "float", "date", "datetime", "boolean"]
DATE_TYPES = ("date", "datetime")     # "date" keeps the calendar day only; "datetime" also keeps the time
MissingPolicy = Literal["quarantine", "keep_and_flag", "fill_value", "derive", "fill_from_group", "impute",
                        "placeholder"]
RuleKind = Literal["formula", "same_sign", "not_equal", "date_range"]
Severity = Literal["quarantine", "flag"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")   # a typo in YAML becomes an error, not a silent no-op


class ColumnSpec(Strict):
    name: str = ""
    type: ColumnType
    required: bool = False
    nullable: bool = True
    missing_policy: MissingPolicy = "keep_and_flag"
    fill_value: Any = None
    min: float | None = None
    max: float | None = None
    allowed_values: list[str] | None = None
    aliases: list[str] = Field(default_factory=list)
    normalize_case: bool = False      # "NORTH"/" north " -> the known/most common spelling
    money: bool = False               # an amount in the dataset currency (used by currency conversion)
    derive_expression: str | None = None   # used when missing_policy == "derive", e.g. "Sales / Quantity"
    derive_round: int | None = None
    placeholder: str = "MISSING-ROW-{row}"        # missing_policy placeholder: {row} = row in the original file
    group_by: list[str] = Field(default_factory=list)   # fill_from_group: copy the value other rows of the group agree on
    impute_method: Literal["median", "mean", "mode"] | None = None
    max_skew_for_mean: float = 1.0                       # mean imputation refused if |skewness| is above this
    description: str = ""

    @model_validator(mode="after")
    def _check(self):
        if self.missing_policy == "derive":
            if not self.derive_expression:
                raise ValueError(f"{self.name}: missing_policy derive needs derive_expression")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*|[A-Za-z0-9_.\s+\-*/()]+", self.derive_expression):
                raise ValueError(f"{self.name}: derive_expression may only use columns, numbers and + - * / ( )")
        if self.missing_policy == "fill_from_group" and not self.group_by:
            raise ValueError(f"{self.name}: missing_policy fill_from_group needs group_by")
        if self.missing_policy == "impute":
            if not self.impute_method:
                raise ValueError(f"{self.name}: missing_policy impute needs impute_method")
            if self.impute_method in ("median", "mean") and self.type not in ("integer", "float"):
                raise ValueError(f"{self.name}: {self.impute_method} imputation only applies to numeric columns")
        if not self.nullable and self.missing_policy == "keep_and_flag":
            raise ValueError(f"{self.name}: conflict: not nullable but missing_policy keep_and_flag")
        if self.allowed_values is not None and not self.allowed_values:
            raise ValueError(f"{self.name}: allowed_values is empty")
        if self.normalize_case and self.type != "string":
            raise ValueError(f"{self.name}: normalize_case only applies to string columns")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"{self.name}: min {self.min} > max {self.max}")
        if self.missing_policy == "fill_value" and self.fill_value is None:
            raise ValueError(f"{self.name}: missing_policy fill_value needs fill_value")
        if (self.min is not None or self.max is not None) and self.type not in ("integer", "float"):
            raise ValueError(f"{self.name}: min/max only apply to numeric columns")
        return self


class RuleSpec(Strict):
    id: str = ""
    kind: RuleKind
    description: str = ""
    severity: Severity = "flag"
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)

    def referenced_columns(self) -> set[str]:
        p = self.params
        cols = set(p.get("columns", []))
        for k in ("column", "target"):
            if k in p:
                cols.add(p[k])
        if "expression" in p:
            cols |= set(re.findall(r"[A-Z][A-Za-z_]*", p["expression"]))
        return cols


class LocaleSpec(Strict):
    description: str = ""
    currency_symbol: str
    currency_code: str
    date_order: Literal["DMY", "MDY", "YMD"]
    date_format: str
    decimal_separator: str
    thousands_separator: str
    grouping: Literal["indian", "international"]
    magnitudes: dict[str, float]
    languages: list[str] = Field(default_factory=lambda: ["en"])      # for written dates ("5 मार्च 2025")
    timezone_abbreviations: dict[str, str] = Field(default_factory=dict)   # e.g. IST -> Asia/Kolkata (India)

    @model_validator(mode="after")
    def _check(self):
        if self.decimal_separator == self.thousands_separator:
            raise ValueError("decimal and thousands separators must differ")
        return self


class PartialDatePolicy(Strict):
    """How to complete 'Mar 2025' (no day) and '05/03' (no year). See normalization/partial_dates.py."""
    missing_day: Literal["first_of_month", "last_of_month", "fixed_day", "median_day", "mean_day", "mode_day",
                         "previous_row", "next_row", "plugin", "quarantine"] = "first_of_month"
    missing_year: Literal["mode_year", "previous_row", "next_row", "fixed_year", "plugin", "quarantine"] = "mode_year"
    fixed_day: int = Field(1, ge=1, le=31)
    fixed_year: int | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.missing_year == "fixed_year" and not self.fixed_year:
            raise ValueError("partial_dates: missing_year fixed_year needs fixed_year")
        return self


class Policies(Strict):
    null_markers: list[str]
    strip_whitespace: bool = True
    collapse_inner_spaces: bool = True
    categorical_case: Literal["match_known", "keep"] = "match_known"
    ambiguous_dates: Literal["use_locale", "quarantine"] = "use_locale"
    extra_date_formats: list[str] = Field(default_factory=list)
    excel_serial_dates: bool = True
    two_digit_years: bool = True          # 05/03/26 -> 2026 (Python pivot: 00-68 -> 20xx, 69-99 -> 19xx)
    unix_timestamps: bool = True          # 1741132800 (s / ms / µs, UTC); only accepted inside date_range
    compact_dates: bool = True            # 20250305; only accepted inside date_range
    dateparser_fallback: bool = True      # written dates via dateparser ("5th March 2025"), strict, in range
    partial_dates: PartialDatePolicy = Field(default_factory=PartialDatePolicy)
    timezone: str | None = None           # business time zone, e.g. Asia/Kolkata; needed for "...+05:30"/"Z" times
    percent_strings: bool = True
    accounting_negatives: bool = True
    magnitude_suffixes: bool = True
    invalid_value_action: Literal["quarantine"] = "quarantine"
    max_quarantine_share: float = Field(0.2, ge=0, le=1)
    max_file_mb: float = Field(50, gt=0)
    header_rows: int = Field(1, ge=1, le=5)    # 2 = two-row header ("Sales" over "Q1 | Q2" -> "Sales Q1")
    large_files: Literal["auto", "always", "never"] = "auto"   # chunked mode (DuckDB) for files too big for RAM
    chunk_rows: int = Field(50_000, ge=10)
    duckdb_memory_mb: int = Field(256, ge=64)
    max_chunked_file_mb: float = Field(5_000, gt=0)


    @model_validator(mode="after")
    def _check_tz(self):
        if self.timezone:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError) as e:
                raise ValueError(f"unknown timezone {self.timezone!r}") from e
        return self


class DuplicatePolicy(Strict):
    exact: Literal["drop", "flag"] = "drop"
    key: list[str] = Field(default_factory=list)
    key_conflict: Literal["flag", "quarantine"] = "flag"


class Business(Strict):
    returns_allowed: bool = False
    negative_profit_allowed: bool = True


class CurrencyPolicy(Strict):
    foreign_amounts: Literal["refuse", "convert"] = "refuse"   # e.g. "US$100" in an INR dataset
    reporting_currency: str | None = None    # add <column>_<CODE> copies of money columns, e.g. Sales_USD
    rate_date_column: str | None = None      # which date's rate to use (the transaction date)
    max_rate_age_days: int = Field(7, ge=0, le=31)   # weekends/holidays: last rate up to N days earlier


class DateRange(Strict):
    min: date
    max: date


class DatasetConfig(Strict):
    dataset_id: str
    domain: str
    description: str = ""
    locale_name: str
    locale: LocaleSpec
    date_range: DateRange
    policies: Policies
    duplicates: DuplicatePolicy
    columns: dict[str, ColumnSpec]
    rules: dict[str, RuleSpec]
    business: Business = Field(default_factory=Business)
    currency: CurrencyPolicy = Field(default_factory=CurrencyPolicy)
    plugins: list[str] = Field(default_factory=list)    # add-on modules, e.g. ["plugins.sales_sanity"]

    @model_validator(mode="after")
    def _check(self):
        names = set(self.columns)
        for rid, rule in self.rules.items():
            unknown = rule.referenced_columns() - names
            if unknown:
                raise ValueError(f"rule {rid!r} uses unknown column(s): {sorted(unknown)}")
        for col, spec in self.columns.items():
            if spec.derive_expression:
                used = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", spec.derive_expression))
                if used - names:
                    raise ValueError(f"{col}: derive_expression uses unknown column(s): {sorted(used - names)}")
                if col in used:
                    raise ValueError(f"{col}: derive_expression refers to itself")
        for col, spec in self.columns.items():
            if set(spec.group_by) - names or col in spec.group_by:
                raise ValueError(f"{col}: group_by must list other existing columns")
        for name in self.plugins:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", name):
                raise ValueError(f"invalid plugin module name {name!r}")
        c = self.currency
        if c.foreign_amounts == "convert" or c.reporting_currency:
            col = c.rate_date_column
            if not col or col not in self.columns or self.columns[col].type not in DATE_TYPES:
                raise ValueError("currency conversion needs rate_date_column = an existing date column")
            if not any(s.money for s in self.columns.values()):
                raise ValueError("currency conversion needs at least one column with money: true")
        if c.reporting_currency and not re.fullmatch(r"[A-Z]{3}", c.reporting_currency):
            raise ValueError(f"reporting_currency must be a 3-letter ISO code, got {c.reporting_currency!r}")
        unknown = set(self.duplicates.key) - names
        if unknown:
            raise ValueError(f"duplicate key uses unknown column(s): {sorted(unknown)}")
        if self.date_range.min > self.date_range.max:
            raise ValueError("date_range min is after max")
        seen: dict[str, str] = {}
        for col, spec in self.columns.items():
            for alias in {normalize_header(col), *map(normalize_header, spec.aliases)}:
                if alias in seen and seen[alias] != col:
                    raise ValueError(f"alias {alias!r} maps to both {seen[alias]} and {col}")
                seen[alias] = col
        return self

    def header_map(self) -> dict[str, str]:
        """normalized header text -> canonical column name"""
        out = {}
        for col, spec in self.columns.items():
            for alias in [col, *spec.aliases]:
                out[normalize_header(alias)] = col
        return out

    def canonical_name(self, header: str) -> str | None:
        return self.header_map().get(normalize_header(header))

    @property
    def required_columns(self) -> list[str]:
        return [c for c, s in self.columns.items() if s.required]


def normalize_header(text: str) -> str:
    """' Unit Price (INR) ' -> 'unit_price_inr'"""
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")


def deep_merge(base: dict, override: dict) -> dict:
    """Override wins; nested dicts are merged key by key; lists are replaced."""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_dataset_config(dataset_id: str, config_dir: Path = CONFIG_DIR) -> DatasetConfig:
    dataset = _read(config_dir / "datasets" / f"{dataset_id}.yaml")
    domain = _read(config_dir / "domains" / f"{dataset['domain']}.yaml")
    merged = deep_merge(deep_merge(_read(config_dir / "default.yaml"), domain), dataset)

    locales = _read(config_dir / "locales.yaml")
    name = merged.pop("locale")
    if name not in locales:
        raise ValueError(f"unknown locale {name!r}; known: {sorted(locales)}")
    merged["locale_name"], merged["locale"] = name, locales[name]

    for col, spec in merged.get("columns", {}).items():
        spec["name"] = col
    for rid, rule in merged.get("rules", {}).items():
        rule["id"] = rid
    return DatasetConfig.model_validate(merged)
