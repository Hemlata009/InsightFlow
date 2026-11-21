"""Shared logic: turn a clean "truth" table into a messy copy plus an answer key.

Every planted mistake is recorded with the row it is in (`messy_row`, 0-based data row in the messy
file), the true row (`source_row_id`), the messy value, the correct value and the expected action.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

CORE_COLUMNS = [
    "Order_ID", "Order_Date", "Customer_ID", "Product", "Category", "Region",
    "Quantity", "Unit_Price", "Sales", "Discount", "Profit",
]
EXTRA_COLUMNS = ["Sub_Category", "Segment", "State"]
COLUMNS = ["source_row_id", *CORE_COLUMNS, *EXTRA_COLUMNS]

LOCALES = {
    "en_US": {"currency": "$", "date_fmt": "%m/%d/%Y", "grouping": "international"},
    "en_IN": {"currency": "₹", "date_fmt": "%d/%m/%Y", "grouping": "indian"},
}
NULL_MARKERS = ["NA", "N/A", "NULL", "-", ""]
EXCEL_EPOCH = date(1899, 12, 30)


# ---------- number formatting ----------
def plain(v: float) -> str:
    """Native, unformatted number text (what a clean export would contain)."""
    if float(v).is_integer():
        return str(int(v))
    return format(float(v), ".10g")


def _decimals(v: float) -> int:
    """Decimals needed to write v exactly (at least 2), so formatting never rounds the true value."""
    text = plain(v)
    return max(2, len(text.split(".")[1]) if "." in text else 0)


def group_international(v: float) -> str:
    return f"{v:,.{_decimals(v)}f}"


def group_indian(v: float) -> str:
    """1234567.5 -> '12,34,567.50' (lakh/crore grouping)."""
    sign = "-" if v < 0 else ""
    whole, frac = f"{abs(v):.{_decimals(v)}f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return f"{sign}{whole}.{frac}"


def with_magnitude(v: float, grouping: str) -> str:
    """Exact short form: 1534.2 -> '1.5342K', 123456.78 -> '1.2345678 L'."""
    a = abs(v)
    if grouping == "indian":
        scale, suffix = ((1e7, " Cr") if a >= 1e7 else (1e5, " L") if a >= 1e5 else (1e3, "K"))
    else:
        scale, suffix = ((1e6, "M") if a >= 1e6 else (1e3, "K"))
    decimals = _decimals(v) + int(round(np.log10(scale)))
    text = f"{v / scale:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


# ---------- the corruption plan ----------
# (issue_type, column, expected_action, eligibility filter on the truth row or None)
PLAN = [
    ("null_marker", "Customer_ID", "flag_missing", None),
    ("null_marker", "Region", "flag_missing", None),
    ("null_marker", "Discount", "flag_missing", None),
    ("date_iso", "Order_Date", "normalize", None),
    ("date_month_name", "Order_Date", "normalize", None),
    ("date_excel_serial", "Order_Date", "normalize", None),
    ("date_out_of_range", "Order_Date", "quarantine", None),
    ("currency_grouped", "Sales", "normalize", lambda r: abs(r["Sales"]) >= 1000),
    ("magnitude_suffix", "Sales", "normalize", lambda r: abs(r["Sales"]) >= 1000),
    ("accounting_negative", "Profit", "normalize", lambda r: r["Profit"] < 0),
    ("percent_string", "Discount", "normalize", lambda r: r["Discount"] > 0),
    ("non_numeric_text", "Unit_Price", "repair_from_formula", None),
    ("invalid_quantity", "Quantity", "quarantine", None),
    ("invalid_discount", "Discount", "repair_from_formula", None),
    ("whitespace_case", "Product", "normalize", None),
    ("whitespace_case", "Region", "normalize", None),
    ("exact_duplicate", None, "deduplicate", None),
    ("hidden_duplicate", None, "normalize_then_deduplicate", None),
]


def native_text(row: pd.Series, locale: str) -> dict:
    """The row as a clean export in its locale would write it (all strings)."""
    fmt = LOCALES[locale]["date_fmt"]
    out = {}
    for col in COLUMNS[1:]:
        v = row[col]
        if col == "Order_Date":
            out[col] = pd.Timestamp(v).strftime(fmt)
        elif isinstance(v, (int, float, np.integer, np.floating)):
            out[col] = plain(v)
        else:
            out[col] = str(v)
    return out


def corrupt_value(issue: str, col: str, row: pd.Series, locale: str, rng) -> str:
    loc = LOCALES[locale]
    v = row[col] if col else None
    if issue == "null_marker":
        return NULL_MARKERS[int(rng.integers(len(NULL_MARKERS)))]
    if issue == "date_iso":
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    if issue == "date_month_name":
        return pd.Timestamp(v).strftime("%d-%b-%y")
    if issue == "date_excel_serial":
        return str((pd.Timestamp(v).date() - EXCEL_EPOCH).days)
    if issue == "date_out_of_range":
        return pd.Timestamp(v).replace(year=2035).strftime(loc["date_fmt"])
    if issue == "currency_grouped":
        g = group_indian(v) if loc["grouping"] == "indian" else group_international(v)
        return f"{loc['currency']}{g}"
    if issue == "magnitude_suffix":
        return with_magnitude(v, loc["grouping"])
    if issue == "accounting_negative":
        g = group_indian(abs(v)) if loc["grouping"] == "indian" else group_international(abs(v))
        return f"({g})"
    if issue == "percent_string":
        return f"{v * 100:g}%"
    if issue == "non_numeric_text":
        return ["abc", "#VALUE!", "price?", "TBD"][int(rng.integers(4))]
    if issue == "invalid_quantity":
        return "-999"
    if issue == "invalid_discount":
        return "1.5"
    if issue == "whitespace_case":
        s = str(v)
        return [f"  {s.lower()} ", f"{s.upper()}  ", f" {s.title()}"][int(rng.integers(3))]
    raise ValueError(issue)


def expected_of(issue: str, col: str | None, row: pd.Series):
    if col is None:
        return None
    v = row[col]
    if col == "Order_Date":
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v)
    return v


def make_messy(truth: pd.DataFrame, locale: str, seed: int, rate: float = 0.004,
               expected_overrides: dict | None = None):
    """expected_overrides: issue_type -> expected_action that differs for this dataset's rules."""
    """Return (messy_df with canonical column names, planted_issue_list)."""
    rng = np.random.default_rng(seed)
    n = len(truth)
    per_issue = max(3, round(n * rate))
    order = list(rng.permutation(n))
    used: set[int] = set()
    assignments: dict[int, tuple] = {}   # truth index -> (issue, col, action)

    for issue, col, action, cond in PLAN:
        action = (expected_overrides or {}).get(issue, action)
        picked = 0
        for idx in order:
            if picked == per_issue:
                break
            if idx in used or (cond and not cond(truth.iloc[idx])):
                continue
            used.add(idx)
            assignments[idx] = (issue, col, action)
            picked += 1

    rows, issues = [], []
    for idx in range(n):
        t = truth.iloc[idx]
        base = native_text(t, locale)
        sid = int(t["source_row_id"])
        a = assignments.get(idx)
        if a and a[1] is not None:
            issue, col, action = a
            base[col] = corrupt_value(issue, col, t, locale, rng)
            issues.append(_issue(issue, col, action, len(rows), sid, base[col], expected_of(issue, col, t)))
        rows.append(base)
        if a and a[1] is None:   # duplicates go right after the original row
            issue, _, action = a
            dup = dict(base)
            if issue == "hidden_duplicate":
                dup["Region"] = f" {dup['Region'].lower()} "
                dup["Product"] = f"{dup['Product'].upper()} "
            issues.append(_issue(issue, None, action, len(rows), sid, None, None,
                                 note=f"copy of messy_row {len(rows) - 1}"))
            rows.append(dup)

    for i, iss in enumerate(issues, start=1):
        iss["issue_id"] = f"I{i:04d}"
    messy = pd.DataFrame(rows, columns=COLUMNS[1:])
    return messy, issues


def _issue(issue, col, action, messy_row, sid, messy_value, expected, note=""):
    d = {"issue_id": None, "issue_type": issue, "column": col, "messy_row": messy_row,
         "source_row_id": sid, "messy_value": messy_value, "expected_value": expected,
         "expected_action": action}
    if note:
        d["note"] = note
    return d


# ---------- writers ----------
def write_outputs(out_dir: Path, dataset_id: str, truth: pd.DataFrame, messy: pd.DataFrame,
                  issues: list, *, locale: str, header_map: dict, csv_encoding: str,
                  csv_sep: str, source: dict, natural_issues: list, stories: list) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    truth_out = truth.copy()
    truth_out["Order_Date"] = pd.to_datetime(truth_out["Order_Date"]).dt.strftime("%Y-%m-%d")
    truth_out.to_csv(out_dir / "sales_truth.csv", index=False, encoding="utf-8", lineterminator="\n")

    messy_out = messy.rename(columns=header_map)
    messy_out.to_csv(out_dir / "sales_messy.csv", index=False, encoding=csv_encoding, sep=csv_sep,
                     lineterminator="\n")
    _write_excel(out_dir / "sales_messy.xlsx", messy_out, dataset_id)

    counts: dict[str, int] = {}
    for iss in issues:
        counts[iss["issue_type"]] = counts.get(iss["issue_type"], 0) + 1
    key = {
        "dataset_id": dataset_id,
        "locale": locale,
        "source": source,
        "files": {
            "truth": "sales_truth.csv",
            "messy_csv": {"name": "sales_messy.csv", "encoding": csv_encoding, "delimiter": csv_sep},
            "messy_xlsx": {"name": "sales_messy.xlsx", "data_sheet": "Sales", "header_row": 3,
                           "other_sheets": ["Notes"]},
        },
        "rows": {"truth": len(truth), "messy": len(messy)},
        "column_mapping": {v: k for k, v in header_map.items()},
        "natural_issues": natural_issues,
        "stories": stories,
        "planted_issue_counts": dict(sorted(counts.items())),
        "planted_issues": issues,
    }
    with open(out_dir / "answer_key.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, indent=2, ensure_ascii=False)
    return key


def _write_excel(path: Path, df: pd.DataFrame, dataset_id: str) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame({"About": [f"{dataset_id} messy sample export",
                                "Data is on sheet 'Sales'; the header is on row 3."]}
                     ).to_excel(xw, sheet_name="Notes", index=False)
        df.to_excel(xw, sheet_name="Sales", index=False, startrow=2)
        ws = xw.sheets["Sales"]
        ws["A1"] = f"{dataset_id} - Sales export"
        ws["A2"] = "Generated by InsightFlow sample data script"
        xw.book.properties.created = datetime(2026, 1, 1)
        xw.book.properties.modified = datetime(2026, 1, 1)
