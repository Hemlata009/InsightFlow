"""Health check BEFORE any change: what is in each column, and what looks wrong.

    report = profile(result.data, cfg, result.metadata)   # plain dict, JSON-ready
    write_report(report, "data/processed/SALES_002/profile_report.json")
    print(summary_text(report))
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from insightflow.config import DatasetConfig, normalize_header
from insightflow.ingestion import SOURCE_ROW

from .patterns import EXCEL_SERIAL_RANGE, FAMILY, PLAIN_NUMBER, classify, slash_date_parts

EXPECTED_FAMILY = {"integer": "numeric", "float": "numeric", "date": "date", "boolean": "boolean"}
N_EXAMPLES = 3


def profile(df: pd.DataFrame, cfg: DatasetConfig | None = None, metadata=None) -> dict:
    data = df.drop(columns=[SOURCE_ROW], errors="ignore")
    null_markers = set(cfg.policies.null_markers) if cfg else {"", "NA", "N/A", "NULL", "null", "-"}
    header_map = cfg.header_map() if cfg else {}

    mapping = {c: header_map.get(normalize_header(c)) for c in data.columns}
    mapped = {c: m for c, m in mapping.items() if m}
    required = cfg.required_columns if cfg else []

    columns = {raw: _profile_column(data[raw], raw, mapping[raw], cfg, null_markers) for raw in data.columns}

    exact_dups = int(data.duplicated().sum())
    simplified = data.apply(lambda s: s.astype("string").str.strip().str.lower().str.replace(r"\s+", " ", regex=True))
    loose_dups = int(simplified.duplicated().sum())

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_id": cfg.dataset_id if cfg else None,
        "source": metadata.to_dict() if metadata is not None else None,
        "rows": int(len(data)),
        "column_count": int(data.shape[1]),
        "header_mapping": {
            "mapped": mapped,
            "unmapped": [c for c, m in mapping.items() if not m],
            "missing_required": [c for c in required if c not in mapped.values()],
            "mapped_more_than_once": sorted({m for m in mapped.values() if list(mapped.values()).count(m) > 1}),
        },
        "duplicates": {
            "exact_rows": exact_dups,
            "rows_duplicate_after_trim_and_case": loose_dups,
            "hidden_duplicates_estimate": loose_dups - exact_dups,
        },
        "columns": columns,
    }
    report["findings"] = _findings(report)
    return report


def _profile_column(s: pd.Series, raw: str, canonical: str | None, cfg, null_markers) -> dict:
    text = s.astype("string").fillna("")
    n = len(text)
    stripped = text.str.strip()
    is_null = text.isin(null_markers) | stripped.eq("") | stripped.isin(null_markers)
    markers = text[is_null].value_counts()
    values = text[~is_null]
    patterns = classify(values)
    counts = patterns.value_counts()

    spec = cfg.columns.get(canonical) if (cfg and canonical) else None
    col = {
        "raw_name": raw,
        "canonical": canonical,
        "expected_type": spec.type if spec else None,
        "rows": n,
        "missing": int(is_null.sum()),
        "missing_share": round(float(is_null.mean()), 4) if n else 0.0,
        "null_markers": {repr(k) if k == "" else k: int(v) for k, v in markers.items()},
        "unique": int(values.nunique()),
        "top_values": {k: int(v) for k, v in values.value_counts().head(5).items()},
        "patterns": {k: int(v) for k, v in counts.items()},
        "pattern_examples": {k: values[patterns == k].unique()[:N_EXAMPLES].tolist() for k in counts.index},
        "leading_trailing_spaces": int((values != values.str.strip()).sum()),
        "formula_like": int(_formula_like(values).sum()),
        "formula_like_examples": values[_formula_like(values)].unique()[:N_EXAMPLES].tolist(),
    }
    fams = patterns.map(FAMILY)
    col["dominant_family"] = fams.value_counts().idxmax() if len(fams) else "empty"
    col["dominant_share"] = round(float(fams.value_counts(normalize=True).max()), 4) if len(fams) else 0.0

    if spec is None:
        return col
    want = EXPECTED_FAMILY.get(spec.type)
    if spec.type == "string":
        col.update(_text_checks(values, spec))
        return col

    if want == "numeric":
        bad = ~fams.isin(["numeric"])
        col["needs_normalization"] = int((fams.eq("numeric") & ~patterns.isin(PLAIN_NUMBER)).sum())
        if spec.type == "integer":
            col["decimals_in_integer_column"] = int(patterns.eq("decimal").sum())
        dot_decimal = cfg.locale.decimal_separator == "."
        plain = pd.to_numeric(values[patterns.isin(PLAIN_NUMBER) & dot_decimal], errors="coerce")
        if len(plain):
            col["plain_min"], col["plain_max"] = float(plain.min()), float(plain.max())
        out = pd.Series(False, index=plain.index)
        if spec.min is not None:
            out |= plain < spec.min
        if spec.max is not None:
            out |= plain > spec.max
        col["out_of_range"] = int(out.sum())
        col["out_of_range_examples"] = values[out[out].index].unique()[:N_EXAMPLES].tolist()
    elif want == "date":
        serial = patterns.eq("integer") & pd.to_numeric(values, errors="coerce").between(*EXCEL_SERIAL_RANGE)
        bad = ~(fams.eq("date") | serial)
        col["possible_excel_serial"] = int(serial.sum())
        col.update(_date_checks(values[patterns.eq("date_slash")], cfg))
    else:
        bad = ~fams.eq(want)
    col["type_mismatch"] = int(bad.sum())
    col["type_mismatch_examples"] = values[bad].unique()[:N_EXAMPLES].tolist()
    return col


def _formula_like(values: pd.Series) -> pd.Series:
    """Text that Excel could run as a formula (=, +, -, @ at the start), but not plain numbers like -500."""
    starts = values.str.match(r"^\s*[=+\-@]").fillna(False).astype(bool)
    numeric = values.str.fullmatch(r"\s*[+\-]?[\d.,]+\s*%?").fillna(False).astype(bool)
    return starts & ~numeric


def _text_checks(values: pd.Series, spec) -> dict:
    key = values.str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
    # The most frequent spelling within each loose group is the "reference" spelling (vectorized).
    pairs = pd.DataFrame({"k": key, "v": values}).value_counts().reset_index(name="n")
    reference = (pairs.sort_values(["n", "v"], ascending=[False, True], kind="stable")
                 .drop_duplicates("k").set_index("k")["v"])
    variant = values != key.map(reference)
    out = {"inconsistent_spelling": int(variant.sum()),
           "inconsistent_spelling_examples": values[variant].unique()[:N_EXAMPLES].tolist()}
    if spec.allowed_values:
        allowed_loose = {a.lower() for a in spec.allowed_values}
        unknown = ~key.isin(allowed_loose)
        out["not_in_allowed_values"] = int(unknown.sum())
        out["not_in_allowed_examples"] = values[unknown].unique()[:N_EXAMPLES].tolist()
    return out


def _date_checks(slash: pd.Series, cfg) -> dict:
    if slash.empty:
        return {"ambiguous_day_month": 0, "slash_dates_outside_date_range": 0}
    p = slash_date_parts(slash)
    ambiguous = int(((p["a"] <= 12) & (p["b"] <= 12) & (p["a"] != p["b"])).sum())
    lo, hi = cfg.date_range.min.year, cfg.date_range.max.year
    outside = (p["year"] < lo) | (p["year"] > hi)
    return {"date_order_used": cfg.locale.date_order,
            "ambiguous_day_month": ambiguous,
            "slash_dates_outside_date_range": int(outside.sum()),
            "outside_range_examples": slash[outside.fillna(False)].unique()[:N_EXAMPLES].tolist()}


def _findings(report: dict) -> list[dict]:
    """Short, human-readable list of what needs attention."""
    f = []
    add = lambda sev, col, msg: f.append({"severity": sev, "column": col, "message": msg})   # noqa: E731
    hm = report["header_mapping"]
    for c in hm["missing_required"]:
        add("error", c, "required column not found in the file")
    for c in hm["unmapped"]:
        add("info", c, "column not in the rule book (kept, not validated)")
    d = report["duplicates"]
    if d["exact_rows"]:
        add("warning", None, f"{d['exact_rows']} exact duplicate row(s)")
    if d["hidden_duplicates_estimate"] > 0:
        add("warning", None, f"{d['hidden_duplicates_estimate']} more duplicate row(s) hidden by spaces/case")

    for raw, c in report["columns"].items():
        name = c["canonical"] or raw
        if c["missing"]:
            add("warning", name, f"{c['missing']} missing value(s) using markers {list(c['null_markers'])}")
        if c.get("formula_like"):
            add("warning", name, f"{c['formula_like']} cell(s) start with = + - @ and could run as formulas "
                                  f"if opened in Excel (CSV injection), e.g. {c['formula_like_examples']}")
        if c.get("type_mismatch"):
            add("error", name, f"{c['type_mismatch']} value(s) don't look like {c['expected_type']}, "
                                f"e.g. {c['type_mismatch_examples']}")
        if c.get("needs_normalization"):
            kinds = {k: v for k, v in c["patterns"].items() if k not in PLAIN_NUMBER and FAMILY[k] == "numeric"}
            add("info", name, f"{c['needs_normalization']} number(s) need converting: {kinds}")
        if c.get("out_of_range"):
            add("error", name, f"{c['out_of_range']} value(s) outside the allowed range, e.g. {c['out_of_range_examples']}")
        if c.get("possible_excel_serial"):
            add("info", name, f"{c['possible_excel_serial']} value(s) look like Excel date numbers")
        other_dates = {k: v for k, v in c["patterns"].items() if k in ("date_iso", "date_month_name")}
        if c["expected_type"] == "date" and other_dates:
            add("info", name, f"mixed date styles: {other_dates}")
        if c.get("slash_dates_outside_date_range"):
            add("error", name, f"{c['slash_dates_outside_date_range']} date(s) outside the business date range, "
                                f"e.g. {c['outside_range_examples']}")
        if c.get("inconsistent_spelling"):
            add("warning", name, f"{c['inconsistent_spelling']} value(s) differ only by spaces/case, "
                                  f"e.g. {c['inconsistent_spelling_examples']}")
        if c.get("not_in_allowed_values"):
            add("error", name, f"{c['not_in_allowed_values']} value(s) not in the allowed list, "
                                f"e.g. {c['not_in_allowed_examples']}")
    return f


def write_report(report: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def summary_text(report: dict) -> str:
    lines = [f"Profile of {report['dataset_id'] or 'dataset'}: {report['rows']} rows, {report['column_count']} columns"]
    sev_order = {"error": 0, "warning": 1, "info": 2}
    for item in sorted(report["findings"], key=lambda x: sev_order[x["severity"]]):
        col = f"{item['column']}: " if item["column"] else ""
        lines.append(f"  [{item['severity'].upper():7}] {col}{item['message']}")
    return "\n".join(lines)
