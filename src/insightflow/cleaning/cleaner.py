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


CONFLICT = object()     # marker: the rows of a group disagree on the value


def clean(norm: NormalizeResult, cfg: DatasetConfig, *, dedupe: bool = True,
          group_values: dict | None = None) -> CleanResult:
    """dedupe=False: skip steps (3)-(4); chunked mode does them across all chunks in DuckDB.
    group_values: {column: {group key: value | CONFLICT}} learned from the WHOLE file (chunked mode)."""
    df = norm.data.copy()
    reasons: dict[int, list[str]] = {}

    def quarantine(rows, reason):
        for r in rows:
            reasons.setdefault(int(r), []).append(reason)

    # (1) values that could not be converted. In a fill_from_group column (e.g. Region) an invalid value is
    # treated like a blank first: if the group (e.g. the same State) agrees on a valid value, it replaces it.
    group_cols = {c for c, s in cfg.columns.items() if s.missing_policy == "fill_from_group" and c in df}
    replaced: dict[tuple[int, str], str] = {}               # (row, column) -> why the original was invalid
    for iss in norm.issues:
        if iss["column"] in group_cols:
            replaced[(iss["source_row"], iss["column"])] = iss["reason"]
        else:
            quarantine([iss["source_row"]], f"invalid_value:{iss['column']}:{iss['reason']}")
    for col in group_cols:                                  # values the rule book doesn't allow ("Mars")
        bad_value = df[col].notna() & ~_valid_for(df[col], cfg.columns[col])
        for i in df.index[bad_value]:
            replaced[(int(df.at[i, SOURCE_ROW]), col)] = f"not_allowed:{df.at[i, col]}"
            df.at[i, col] = pd.NA

    actions, flags = [], list(getattr(norm, "flags", []))     # flags raised while standardizing
    # (2) missing values, column by column (derivations first need the other columns, so do them last)
    ordered = sorted((c for c in cfg.columns if c in df), key=lambda c: cfg.columns[c].missing_policy == "derive")
    invalid_cells = {(i["source_row"], i["column"]) for i in norm.issues} - set(replaced)
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
        elif policy == "placeholder":                   # e.g. a temporary order ID, always flagged
            for i in df.index[missing]:
                r = int(df.at[i, SOURCE_ROW])
                value = spec.placeholder.format(row=r)
                df.at[i, col] = value
                actions.append(_act("placeholder", r, col, None, value))
                flags.append({"stage": "clean", "flag": "placeholder_value", "source_row": r, "column": col,
                              "detail": f"temporary value {value!r}: the original was missing"})
        elif policy == "fill_value":
            df.loc[missing, col] = spec.fill_value
            actions += [_act("fill_value", r, col, None, spec.fill_value) for r in rows]
        elif policy == "fill_from_group":
            a, f, bad_rows = _fill_from_group(df, col, spec.group_by, missing,
                                              (group_values or {}).get(col), spec)
            for act in a:                       # was it a blank, or an invalid value we replaced?
                why = replaced.get((act["source_row"], col))
                if why:
                    act["rule"] = "invalid_replaced_from_group"
                    act["detail"] = f"original was invalid ({why}); {act.get('detail', '')}".strip("; ")
                    flags.append({"stage": "clean", "flag": "invalid_value_replaced", "source_row": act["source_row"],
                                  "column": col, "detail": act["detail"]})
            actions += a
            for r in bad_rows:                  # the group disagrees
                if spec.nullable and (int(r), col) not in replaced:   # unknown but allowed blank: keep + flag (BR-5)
                    flags.append({"stage": "clean", "flag": "group_values_conflict", "source_row": int(r),
                                  "column": col, "detail": "rows of the group disagree; left blank"})
                else:
                    quarantine([r], f"group_values_conflict:{col}")
            for x in f:                         # nothing in the group to copy
                key = (x["source_row"], col)
                if key in replaced:             # an invalid value we could not replace: set aside as invalid
                    quarantine([x["source_row"]], f"invalid_value:{col}:{replaced[key]}")
                elif spec.nullable:
                    flags.append(x)             # a blank that may stay blank: keep + flag
                else:                           # a required value that can't be filled: set the row aside
                    quarantine([x["source_row"]], f"missing_required:{col}")
        elif policy == "impute":
            a, f = _impute(df, col, spec, missing)
            actions += a
            flags += f
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

    if not dedupe:
        empty = pd.DataFrame({SOURCE_ROW: pd.Series(dtype="int64"), "duplicate_of": pd.Series(dtype="int64")})
        return CleanResult(kept.reset_index(drop=True), q.reset_index(drop=True), empty, actions, flags)

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


def group_keys(df: pd.DataFrame, group_by: list[str]) -> pd.Series:
    """One text key per row for the group columns; NA when any group column is blank (no group)."""
    keys = df[group_by].astype("string")
    no_key = keys.isna().any(axis=1)
    joined = keys[group_by[0]].fillna("")               # vectorized (row-wise "|".join was the slowest step)
    for c in group_by[1:]:
        joined = joined.str.cat(keys[c].fillna(""), sep="|")
    return joined.where(~no_key)


def group_value_map(df: pd.DataFrame, col: str, group_by: list[str], into: dict | None = None,
                    spec=None) -> dict:
    """{group key: the value its rows agree on | CONFLICT}; can be updated piece by piece.
    Values that break the column's own rules (not an allowed value, out of range) don't count: one typo
    like Region "Mars" must not block filling for a whole state."""
    out = {} if into is None else into
    keys = group_keys(df, group_by)
    known = df[col].notna() & keys.notna() & _valid_for(df[col], spec)
    for k, v in zip(keys[known], df.loc[known, col]):
        prev = out.get(k, None)
        if prev is None:
            out[k] = v
        elif prev is not CONFLICT and prev != v:
            out[k] = CONFLICT
    return out


def _valid_for(values: pd.Series, spec) -> pd.Series:
    ok = pd.Series(True, index=values.index)
    if spec is None:
        return ok
    if spec.allowed_values:
        ok &= values.isin(spec.allowed_values).fillna(False).astype(bool)
    if spec.min is not None:
        ok &= (values >= spec.min).fillna(False).astype(bool)
    if spec.max is not None:
        ok &= (values <= spec.max).fillna(False).astype(bool)
    return ok


def _fill_from_group(df, col, group_by, missing, whole_file: dict | None = None, spec=None):
    """Copy a value from other rows of the same group (e.g. the same order), only if they all agree.
    Never crosses into another group. Conflicting groups are quarantined; empty groups are flagged."""
    actions, flags, conflicts = [], [], []
    row_keys = group_keys(df, group_by)
    stats = whole_file if whole_file is not None else group_value_map(df, col, group_by, spec=spec)
    for i in df.index[missing]:
        k = row_keys[i]
        if pd.isna(k) or k not in stats:
            flags.append({"stage": "clean", "flag": "missing_value_no_group_value", "source_row": int(df.at[i, SOURCE_ROW]),
                          "column": col})
        elif stats[k] is CONFLICT:
            conflicts.append(df.at[i, SOURCE_ROW])
        else:
            value = stats[k]
            df.at[i, col] = value
            actions.append(_act("filled_from_group", df.at[i, SOURCE_ROW], col, None, _plain(value),
                                detail=f"same {'+'.join(group_by)} rows agree"))
    return actions, flags, conflicts


def _impute(df, col, spec, missing):
    known = df.loc[~missing, col]
    rows = df.loc[missing, SOURCE_ROW]
    if known.empty:
        return [], [{"stage": "clean", "flag": "imputation_skipped_no_data", "source_row": int(r), "column": col}
                    for r in rows]
    method = spec.impute_method
    if method == "mode":
        value = known.mode().sort_values().iloc[0]
    else:
        num = known.astype("float64")
        skew = float(num.skew()) if len(num) > 2 else 0.0
        if method == "mean" and abs(skew) > spec.max_skew_for_mean:
            return [], [{"stage": "clean", "flag": "imputation_skipped_skewed", "source_row": int(r), "column": col,
                         "detail": f"skewness {skew:.2f} > {spec.max_skew_for_mean}: the mean would be misleading"}
                        for r in rows]
        value = float(num.median() if method == "median" else num.mean())
        if spec.type == "integer":
            value = int(round(value))
    before = _dist(known)
    df.loc[missing, col] = value
    after = _dist(df[col])
    detail = f"{method}={_plain(value)}; distribution before {before} after {after}"
    return [_act(f"imputed_{method}", r, col, None, _plain(value), detail=detail) for r in rows], []


def _dist(s: pd.Series) -> dict:
    if not pd.api.types.is_numeric_dtype(s):
        return {"n": int(s.notna().sum())}
    f = s.astype("float64")
    return {"n": int(f.notna().sum()), "mean": round(float(f.mean()), 4), "median": round(float(f.median()), 4),
            "std": round(float(f.std()), 4) if f.notna().sum() > 1 else 0.0}


def _plain(v):
    return v.item() if hasattr(v, "item") else v


def _derive(rows: pd.DataFrame, expression: str, digits: int | None) -> pd.Series:
    """Exact Decimal arithmetic per row, rounded half-up once at the end (see insightflow.money)."""
    from insightflow.money import evaluate, quantize

    out = []
    for rec in rows.to_dict(orient="records"):
        d = evaluate(expression, rec)
        if d is not None and digits is not None:
            d = quantize(d, digits)
        out.append(float(d) if d is not None else np.nan)
    return pd.Series(out, index=rows.index, dtype="float64")


def _act(action, row, col, old, new, detail=""):
    d = {"stage": "clean", "rule": action, "source_row": int(row), "column": col, "old": old, "new": new}
    if detail:
        d["detail"] = detail
    return d
