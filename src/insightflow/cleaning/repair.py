"""Repair set-aside rows from a formula, when the answer is PROVEN (one bad value, the others consistent).

The rule book's formula rule (e.g. Sales = Quantity × Unit_Price × (1 − Discount)) links several columns.
If a row was set aside ONLY because one of those columns is unreadable, out of range or inconsistent,
the bad value can be recomputed from the others with that column's `derive_expression`.

A repair is accepted only if:
  * every reason for setting the row aside involves the formula's columns (nothing else is wrong),
  * exactly ONE column's repair makes the row pass every check (two possible fixes = ambiguous = no repair),
  * the repaired row passes the full schema + business rules again.
Repaired rows are kept, FLAGGED, and the original value is in the log. Generic: no column names in code.
"""

from __future__ import annotations

import re

import pandas as pd

from insightflow.ingestion import SOURCE_ROW


def _formula_columns(cfg) -> set[str]:
    cols: set[str] = set()
    for r in cfg.rules.values():
        if r.enabled and r.kind == "formula":
            cols |= r.referenced_columns()
    return cols


def _implicated(reasons: str, formula_cols: set[str]) -> set[str] | None:
    """Columns blamed by the reasons; None if any reason is about something the formula can't fix."""
    out: set[str] = set()
    for reason in [r.strip() for r in reasons.split(";") if r.strip()]:
        cols = set(re.split(r"[:+]", reason)) & formula_cols
        if not cols or reason.startswith(("missing_", "group_values_conflict", "unreadable_row")):
            return None
        out |= cols
    return out


def candidate_rows(norm_data: pd.DataFrame, cleaned, failed_validation: dict) -> pd.DataFrame:
    """Set-aside rows with their standardized values: from the cleaner's output when they failed validation,
    else from the standardized table (they were set aside while cleaning)."""
    in_val = cleaned.data[cleaned.data[SOURCE_ROW].isin(failed_validation)]
    in_clean = set(cleaned.quarantine[SOURCE_ROW].astype(int)) - set(failed_validation)
    from_norm = norm_data[norm_data[SOURCE_ROW].isin(in_clean)]
    cols = list(in_val.columns) if len(in_val.columns) else list(norm_data.columns)
    return pd.concat([in_val, from_norm.reindex(columns=cols)], ignore_index=True)


def add_original_text(log: list, original: pd.DataFrame, header_changes: dict) -> None:
    """Put the value as written in the ORIGINAL file into each repair's `old`."""
    raw_name = {canon: raw for raw, canon in header_changes.items()}
    by_row = original.set_index(SOURCE_ROW)
    for e in log:
        col = raw_name.get(e["column"], e["column"])
        if e["source_row"] in by_row.index and col in by_row.columns:
            e["old"] = by_row.at[e["source_row"], col]


def repair_rows(candidates: pd.DataFrame, reasons: dict[int, str], cfg) -> tuple[pd.DataFrame, list, list]:
    """candidates: standardized rows (bad cells already blank) that were set aside.
    Returns (repaired rows, log entries, flags).

    Batch version: for each repairable column, ALL candidate rows that blame it are recomputed and
    re-validated in ONE call (a big file can have thousands of candidates; one check per row was slow)."""
    from insightflow.money import evaluate, quantize
    from insightflow.validation import validate

    formula_cols = _formula_columns(cfg)
    repairable = {c for c in formula_cols if cfg.columns.get(c) and cfg.columns[c].derive_expression}
    if not repairable or candidates.empty:
        return candidates.iloc[0:0], [], []
    cands = candidates.reset_index(drop=True)
    blamed = {}
    for i, r in enumerate(cands[SOURCE_ROW].astype(int)):
        b = _implicated(reasons.get(r, ""), formula_cols)
        if b and b <= repairable:
            blamed[i] = b
    dtypes = {c: str(cands[c].dtype) for c in cands.columns}
    options: dict[int, list[tuple[str, object]]] = {}
    for col in sorted(repairable):
        spec = cfg.columns[col]
        others = [c for c in formula_cols if c != col]
        idx, values = [], []
        for i, b in blamed.items():
            if col not in b or cands.loc[i, others].isna().any():
                continue
            value = evaluate(spec.derive_expression, {c: cands.at[i, c] for c in others})
            if value is None:
                continue
            if spec.derive_round is not None:
                value = quantize(value, spec.derive_round)
            if spec.type == "integer":
                if value != value.to_integral_value():
                    continue
                value = int(value)
            else:
                value = float(value)
            idx.append(i)
            values.append(value)
        if not idx:
            continue
        trial = cands.loc[idx].copy()
        trial[col] = values
        trial = trial.astype(dtypes)
        v = validate(trial, cfg)                       # ONE check for all rows trying this column
        if v.structural_errors:
            continue
        failing = {f["source_row"] for f in v.failures}  # must pass EVERY check, flags included
        for i, value in zip(idx, values):
            if int(cands.at[i, SOURCE_ROW]) not in failing:
                options.setdefault(i, []).append((col, value))
    fixed, log, flags = [], [], []
    for i, opts in sorted(options.items()):
        if len(opts) != 1:                             # ambiguous: two different fixes fit
            continue
        col, value = opts[0]
        row = cands.loc[i].copy()
        old = row[col]
        row[col] = value
        fixed.append(row)
        r = int(row[SOURCE_ROW])
        log.append({"stage": "clean", "rule": "repaired_from_formula", "source_row": r, "column": col,
                    "old": None if pd.isna(old) else str(old), "new": value,
                    "detail": f"{cfg.columns[col].derive_expression} (was set aside: {reasons.get(r)})"})
        flags.append({"stage": "clean", "flag": "repaired_from_formula", "source_row": r, "column": col,
                      "detail": f"recomputed from the other columns: {value}"})
    out = pd.DataFrame(fixed).astype(dtypes).reset_index(drop=True) if fixed else cands.iloc[0:0]
    return out, log, flags
