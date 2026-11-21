"""Step 6: apply the cleaning policies from the rule book.

Order: (1) rows with values that could not be standardized -> quarantine
       (2) missing values -> quarantine / keep+flag / fill / derive (per column policy)
       (3) exact duplicates -> keep the first, set the rest aside (logged)
       (4) same business key with different values -> flag for review (kept)
Nothing is deleted: every row leaves this step as kept, quarantined or a removed duplicate, with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from insightflow.config import DatasetConfig
from insightflow.ingestion import SOURCE_ROW
from insightflow.normalization import NormalizeResult

REASONS = "_reasons"


@dataclass
class CleanResult:
    data: pd.DataFrame                                  # rows that continue to validation
    quarantine: pd.DataFrame                            # SOURCE_ROW + REASONS
    duplicates: pd.DataFrame                            # SOURCE_ROW + duplicate_of
    actions: list[dict] = field(default_factory=list)   # fills/derivations/removals (with old/new)
    flags: list[dict] = field(default_factory=list)     # kept, but needs a human look


def clean(norm: NormalizeResult, cfg: DatasetConfig) -> CleanResult:
    df = norm.data.copy()
    reasons: dict[int, list[str]] = {}

    def quarantine(rows, reason):
        for r in rows:
            reasons.setdefault(int(r), []).append(reason)

    # (1) values that could not be converted
    for iss in norm.issues:
        quarantine([iss["source_row"]], f"invalid_value:{iss['column']}:{iss['reason']}")

    actions, flags = [], []
    # (2) missing values, column by column (derivations first need the other columns, so do them last)
    ordered = sorted((c for c in cfg.columns if c in df), key=lambda c: cfg.columns[c].missing_policy == "derive")
    invalid_cells = {(i["source_row"], i["column"]) for i in norm.issues}
    for col in ordered:
        spec = cfg.columns[col]
        missing = df[col].isna() & ~df[SOURCE_ROW].map(lambda r, c=col: (r, c) in invalid_cells)
        if not missing.any():
            continue
        rows = df.loc[missing, SOURCE_ROW]
        policy = spec.missing_policy
        if policy == "quarantine":
            quarantine(rows, f"missing_required:{col}")
        elif policy == "keep_and_flag":
            flags += [{"stage": "clean", "flag": "missing_value", "source_row": int(r), "column": col}
                      for r in rows]
        elif policy == "fill_value":
            df.loc[missing, col] = spec.fill_value
            actions += [_act("fill_value", r, col, None, spec.fill_value) for r in rows]
        elif policy == "derive":
            derived = _derive(df.loc[missing], spec.derive_expression, spec.derive_round)
            ok = derived.notna() & np.isfinite(derived.astype("float64").fillna(np.nan))
            ok &= ~df.loc[missing, SOURCE_ROW].isin(reasons.keys())
            df.loc[ok[ok].index, col] = derived[ok].astype(df[col].dtype) if spec.type == "integer" else derived[ok]
            for i in ok[ok].index:
                actions.append(_act("derived", df.at[i, SOURCE_ROW], col, None, float(derived[i]),
                                    detail=spec.derive_expression))
            quarantine(df.loc[ok[~ok].index, SOURCE_ROW], f"missing_not_derivable:{col}")

    bad = df[SOURCE_ROW].isin(reasons.keys())
    q = df.loc[bad, [SOURCE_ROW]].copy()
    q[REASONS] = q[SOURCE_ROW].map(lambda r: "; ".join(reasons[int(r)]))
    kept = df.loc[~bad]

    # (3) exact duplicates (after normalization, so hidden duplicates are caught too)
    value_cols = [c for c in kept.columns if c != SOURCE_ROW]
    dup_mask = kept.duplicated(subset=value_cols, keep="first")
    first_of = kept.groupby(value_cols, dropna=False, sort=False)[SOURCE_ROW].transform("first")
    dups = pd.DataFrame({SOURCE_ROW: kept.loc[dup_mask, SOURCE_ROW],
                         "duplicate_of": first_of[dup_mask]})
    if cfg.duplicates.exact == "drop":
        actions += [_act("duplicate_removed", r, None, None, None, detail=f"same as row {int(f)}")
                    for r, f in zip(dups[SOURCE_ROW], dups["duplicate_of"])]
        kept = kept.loc[~dup_mask]
    else:
        flags += [{"stage": "clean", "flag": "exact_duplicate", "source_row": int(r), "column": None,
                   "detail": f"same as row {int(f)}"} for r, f in zip(dups[SOURCE_ROW], dups["duplicate_of"])]
        dups = dups.iloc[0:0]

    # (4) same key, different values
    key = [k for k in cfg.duplicates.key if k in kept]
    if key:
        conflict = kept.duplicated(subset=key, keep=False) & kept[key].notna().all(axis=1)
        if cfg.duplicates.key_conflict == "quarantine":
            extra = kept.loc[conflict, [SOURCE_ROW]].assign(**{REASONS: "key_conflict:" + "+".join(key)})
            q = pd.concat([q, extra], ignore_index=True)
            kept = kept.loc[~conflict]
        else:
            flags += [{"stage": "clean", "flag": "key_conflict", "source_row": int(r), "column": "+".join(key)}
                      for r in kept.loc[conflict, SOURCE_ROW]]

    return CleanResult(kept.reset_index(drop=True), q.reset_index(drop=True),
                       dups.reset_index(drop=True), actions, flags)


def _derive(rows: pd.DataFrame, expression: str, digits: int | None) -> pd.Series:
    frame = rows.astype({c: "float64" for c in rows.columns if str(rows[c].dtype) in ("Int64", "Float64")})
    with np.errstate(divide="ignore", invalid="ignore"):
        out = frame.eval(expression, engine="python")
    out = pd.to_numeric(out, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return out.round(digits) if digits is not None else out


def _act(action, row, col, old, new, detail=""):
    d = {"stage": "clean", "rule": action, "source_row": int(row), "column": col, "old": old, "new": new}
    if detail:
        d["detail"] = detail
    return d
