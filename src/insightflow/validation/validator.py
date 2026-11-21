"""Step 7: check the cleaned data against the rule book.

Two kinds of checks, both generated from config (no column names in this code):
  * schema (Pandera): required columns, types, nullability, min/max, allowed values
  * business rules: formula, same_sign, not_equal, date_range

    v = validate(clean_result.data, cfg)
    v.structural_errors   # e.g. a required column is missing -> the run fails
    v.failures            # one record per (row, check) with severity "quarantine" or "flag"
    v.quarantine_rows     # rows to set aside
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pandera.pandas as pa

from insightflow.config import DatasetConfig, RuleSpec
from insightflow.ingestion import SOURCE_ROW

PANDERA_DTYPE = {"integer": "Int64", "float": "Float64", "string": "string", "boolean": "boolean"}


@dataclass
class ValidationResult:
    structural_errors: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    @property
    def quarantine_rows(self) -> set[int]:
        return {f["source_row"] for f in self.failures if f["severity"] == "quarantine"}

    @property
    def flagged_rows(self) -> set[int]:
        return {f["source_row"] for f in self.failures if f["severity"] == "flag"}

    def summary(self) -> dict:
        out: dict[str, dict] = {}
        for f in self.failures:
            s = out.setdefault(f["check"], {"severity": f["severity"], "rows": 0})
            s["rows"] += 1
        return out


def build_schema(cfg: DatasetConfig, present: list[str]) -> pa.DataFrameSchema:
    cols = {}
    for name, spec in cfg.columns.items():
        if name not in present:
            continue
        checks = []
        if spec.min is not None:
            checks.append(pa.Check.ge(spec.min))
        if spec.max is not None:
            checks.append(pa.Check.le(spec.max))
        if spec.allowed_values:
            checks.append(pa.Check.isin(spec.allowed_values))
        if spec.type in ("date", "datetime"):
            checks.append(pa.Check(lambda s: pd.api.types.is_datetime64_any_dtype(s), element_wise=False,
                                   name="is_date"))
        cols[name] = pa.Column(PANDERA_DTYPE.get(spec.type), checks, nullable=spec.nullable, required=True)
    return pa.DataFrameSchema(cols, strict=False, coerce=False)


def validate(df: pd.DataFrame, cfg: DatasetConfig) -> ValidationResult:
    res = ValidationResult()
    missing = [c for c in cfg.required_columns if c not in df]
    if missing:
        res.structural_errors.append(f"required column(s) missing: {missing}")
    present = [c for c in cfg.columns if c in df]
    rows = df[SOURCE_ROW] if SOURCE_ROW in df else pd.Series(range(len(df)), index=df.index)

    # ---- schema
    res.checks_run.append("schema")
    try:
        build_schema(cfg, present).validate(df, lazy=True)
    except pa.errors.SchemaErrors as e:
        fc = e.failure_cases
        for _, f in fc.iterrows():
            if pd.isna(f["index"]):        # column-level problem (e.g. wrong dtype)
                res.structural_errors.append(f"{f['column']}: {f['check']} ({f['failure_case']})")
                continue
            res.failures.append(_fail(rows[f["index"]], f"schema:{f['check']}", f["column"],
                                      f["failure_case"], "quarantine"))

    # ---- business rules from config
    for rule in cfg.rules.values():
        if not rule.enabled or not rule.referenced_columns() <= set(df.columns):
            continue
        res.checks_run.append(rule.id)
        bad = _evaluate(rule, df, cfg)
        col = rule.params.get("column") or rule.params.get("target") or "+".join(rule.params.get("columns", []))
        for i in df.index[bad]:
            res.failures.append(_fail(rows[i], f"rule:{rule.id}", col, _value(df, i, rule), rule.severity))
    # Business switches (returns allowed, losses allowed) are expressed as column min/max in the
    # dataset config, so this code never needs to know domain column names.
    return res


def _evaluate(rule: RuleSpec, df: pd.DataFrame, cfg: DatasetConfig) -> pd.Series:
    p = rule.params
    if rule.kind == "formula":
        frame = df.astype({c: "float64" for c in df.columns if str(df[c].dtype) in ("Int64", "Float64")})
        with np.errstate(divide="ignore", invalid="ignore"):
            expected = frame.eval(p["expression"], engine="python")
        target = frame[p["target"]]
        tol = p.get("abs_tolerance", 0.0) + p.get("rel_tolerance", 0.0) * target.abs()
        known = target.notna() & expected.notna()
        return (known & ((target - expected).abs() > tol)).fillna(False).astype(bool)
    if rule.kind == "same_sign":
        a, b = (df[c].astype("Float64") for c in p["columns"])
        known = a.notna() & b.notna()
        return (known & (np.sign(a) != np.sign(b))).fillna(False).astype(bool)
    if rule.kind == "not_equal":
        return df[p["column"]].eq(p["value"]).fillna(False).astype(bool)
    if rule.kind == "date_range":
        d = df[p["column"]]
        lo = pd.Timestamp(cfg.date_range.min)
        end = pd.Timestamp(cfg.date_range.max) + pd.Timedelta(days=1)    # the whole last day is inside
        return (d.notna() & ((d < lo) | (d >= end))).fillna(False).astype(bool)
    raise ValueError(f"unknown rule kind {rule.kind}")


def _value(df, i, rule):
    cols = [c for c in rule.referenced_columns() if c in df]
    return {c: _plain(df.at[i, c]) for c in sorted(cols)}


def _plain(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return v.item() if hasattr(v, "item") else v


def _fail(row, check, column, value, severity):
    return {"stage": "validate", "source_row": int(row), "check": check, "column": column,
            "value": _plain(value) if not isinstance(value, dict) else value, "severity": severity}
