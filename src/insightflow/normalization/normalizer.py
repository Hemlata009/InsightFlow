"""Step 5: standardize raw text into typed values with canonical column names.

    norm = normalize(ingest_result.data, cfg)
    norm.data      # canonical columns, typed (Int64 / Float64 / datetime64 / string) + `_source_row`
    norm.changes   # every non-trivial change: rule, row, column, old text, new value
    norm.issues    # values that could NOT be converted safely (they become blank + a reason)

Rules: never guess, keep the original text in the log, plain values are converted but not logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from insightflow.config import DatasetConfig, normalize_header
from insightflow.ingestion import SOURCE_ROW
from insightflow.profiling.patterns import PLAIN_NUMBER, classify

from .dates import parse_dates
from .numbers import NotConvertible, parse_number

BOOL_TRUE = {"yes", "y", "true", "t", "1"}
BOOL_FALSE = {"no", "n", "false", "f", "0"}


@dataclass
class NormalizeResult:
    data: pd.DataFrame
    changes: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    header_changes: dict[str, str] = field(default_factory=dict)   # raw header -> canonical
    warnings: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)


def normalize(raw: pd.DataFrame, cfg: DatasetConfig) -> NormalizeResult:
    res = NormalizeResult(data=pd.DataFrame(index=raw.index))
    res.data[SOURCE_ROW] = raw[SOURCE_ROW] if SOURCE_ROW in raw else range(1, len(raw) + 1)
    rows = res.data[SOURCE_ROW]

    # 1. headers -> canonical names (first match wins; extra columns are kept as text)
    hmap = cfg.header_map()
    used: dict[str, str] = {}
    for col in raw.columns:
        if col == SOURCE_ROW:
            continue
        canon = hmap.get(normalize_header(col))
        if canon and canon in used.values():
            res.warnings.append(f"column {col!r} also maps to {canon}; kept as {col!r}")
            canon = None
        if canon:
            used[col] = canon
            if col != canon:
                res.header_changes[col] = canon
        else:
            res.warnings.append(f"column {col!r} is not in the rule book; kept as text")
    res.missing_required = [c for c in cfg.required_columns if c not in used.values()]

    nulls = set(cfg.policies.null_markers)
    for col in raw.columns:
        if col == SOURCE_ROW:
            continue
        canon = used.get(col)
        text = raw[col].astype("string")
        # 2. null markers -> real blanks
        stripped = text.str.strip()
        is_null = text.isna() | stripped.eq("") | text.isin(nulls) | stripped.isin(nulls)
        for i in text[is_null & text.notna() & text.ne("")].index:
            res.changes.append(_chg("null_marker", rows[i], canon or col, text[i], None))
        text = text.mask(is_null, pd.NA)
        if canon is None:
            res.data[col] = text
            continue
        spec = cfg.columns[canon]
        if spec.type == "string":
            res.data[canon] = _strings(text, spec, cfg, rows, canon, res)
        elif spec.type in ("integer", "float"):
            res.data[canon] = _numbers(text, spec, cfg, rows, canon, res)
        elif spec.type == "date":
            res.data[canon] = _dates(text, cfg, rows, canon, res)
        else:
            res.data[canon] = _booleans(text, rows, canon, res)

    ordered = [SOURCE_ROW] + [c for c in cfg.columns if c in res.data] + \
              [c for c in res.data if c != SOURCE_ROW and c not in cfg.columns]
    res.data = res.data[ordered]
    return res


def _chg(rule, row, col, old, new):
    return {"stage": "normalize", "rule": rule, "source_row": int(row), "column": col,
            "old": None if old is None else str(old), "new": _jsonable(new)}


def _issue(row, col, value, reason):
    return {"stage": "normalize", "source_row": int(row), "column": col, "value": str(value), "reason": reason}


def _jsonable(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return v.item() if hasattr(v, "item") else v


def _strings(text, spec, cfg, rows, col, res) -> pd.Series:
    out = text
    if cfg.policies.strip_whitespace:
        out = out.str.strip()
    if cfg.policies.collapse_inner_spaces:
        out = out.str.replace(r"\s+", " ", regex=True)
    if spec.normalize_case and cfg.policies.categorical_case == "match_known":
        key = out.str.lower()
        if spec.allowed_values:
            reference = pd.Series({a.lower(): a for a in spec.allowed_values})
        else:   # the most frequent spelling within each group is the reference
            pairs = pd.DataFrame({"k": key, "v": out}).dropna().value_counts().reset_index(name="n")
            reference = (pairs.sort_values(["n", "v"], ascending=[False, True], kind="stable")
                         .drop_duplicates("k").set_index("k")["v"])
        mapped = key.map(reference)
        out = mapped.where(mapped.notna(), out).astype("string")
    changed = out.ne(text).fillna(False) & text.notna()
    for i in text[changed].index:
        res.changes.append(_chg("text_standardized", rows[i], col, text[i], out[i]))
    return out.astype("string")


def _numbers(text, spec, cfg, rows, col, res) -> pd.Series:
    p, loc = cfg.policies, cfg.locale
    pattern = classify(text)
    out = pd.Series(pd.NA, index=text.index, dtype="Float64")
    # Fast path only where "1.5" really means one-point-five, and only for values a float holds exactly.
    plain = text.notna() & pattern.isin(PLAIN_NUMBER) & (loc.decimal_separator == ".")
    plain &= text.str.replace(r"[^0-9]", "", regex=True).str.lstrip("0").str.len().le(15).fillna(False)
    out[plain] = pd.to_numeric(text[plain].str.strip(), errors="coerce").astype("Float64")
    for i in text[text.notna() & ~plain].index:
        try:
            value, how = parse_number(text[i], loc, allow_percent=p.percent_strings,
                                      allow_magnitude=p.magnitude_suffixes,
                                      allow_accounting=p.accounting_negatives)
        except NotConvertible as e:
            res.issues.append(_issue(rows[i], col, text[i], e.reason))
            continue
        out[i] = value
        res.changes.append(_chg(f"number:{how}", rows[i], col, text[i], value))
    if spec.type == "integer":
        not_whole = out.notna() & (out != out.round())
        for i in out[not_whole].index:
            res.issues.append(_issue(rows[i], col, text[i], "not_a_whole_number"))
        out = out.mask(not_whole, pd.NA).round().astype("Int64")
    return out


def _dates(text, cfg, rows, col, res) -> pd.Series:
    dates, rule, reason = parse_dates(text, cfg)
    logged = rule.notna() & rule.ne("locale_format")
    for i in text[logged].index:
        res.changes.append(_chg(f"date:{rule[i]}", rows[i], col, text[i], dates[i]))
    for i in text[reason.notna()].index:
        res.issues.append(_issue(rows[i], col, text[i], reason[i]))
    return dates


def _booleans(text, rows, col, res) -> pd.Series:
    low = text.str.strip().str.lower()
    out = pd.Series(pd.NA, index=text.index, dtype="boolean")
    out[low.isin(BOOL_TRUE)] = True
    out[low.isin(BOOL_FALSE)] = False
    for i in text[text.notna() & out.isna()].index:
        res.issues.append(_issue(rows[i], col, text[i], "not_a_boolean"))
    return out
