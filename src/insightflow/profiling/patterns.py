"""Classify raw text values into patterns (WITHOUT converting them).

    classify(pd.Series(["₹1,00,000", "6K", "(500)", "5%", "2026-03-05", "abc"]))
    -> ["currency", "magnitude", "accounting_negative", "percent", "date_iso", "text"]
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_CUR = r"[₹$€£]"
_NUM = r"\d+(?:\.\d+)?"
# Order matters: the first matching pattern wins.
PATTERNS: list[tuple[str, str]] = [
    ("accounting_negative", rf"\(\s*{_CUR}?\s*[\d,]+(?:\.\d+)?\s*\)"),
    ("percent", rf"-?{_NUM}\s*%"),
    ("magnitude", rf"-?{_CUR}?\s*{_NUM}\s*(?i:k|m|mn|b|bn|l|lakh|lakhs|lac|cr|crore|crores)"),
    ("currency", rf"-?\s*{_CUR}\s*-?[\d,]+(?:\.\d+)?|(?i:inr|usd|eur|gbp)\s*-?[\d,]+(?:\.\d+)?|-?[\d,]+(?:\.\d+)?\s*(?i:inr|usd|eur|gbp)"),
    ("grouped_indian", r"-?\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?"),
    ("grouped_international", r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?"),
    ("grouped_european", r"-?\d{1,3}(?:\.\d{3})+,\d+"),
    ("integer", r"[-+]?\d+"),
    ("decimal", r"[-+]?\d*\.\d+(?:[eE][-+]?\d+)?"),
    ("nan_inf", r"(?i:[-+]?(?:inf|infinity|nan))"),
    ("date_iso", r"\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:\s*(?:Z|[+-]\d{2}:?\d{2}))?)?"),
    ("date_slash", r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?"),
    ("date_month_name", r"\d{1,2}[\s\-]?[A-Za-z]{3,9}[\s\-,]*\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}"),
    ("boolean", r"(?i:yes|no|y|n|true|false)"),
]
FAMILY = {
    "accounting_negative": "numeric", "percent": "numeric", "magnitude": "numeric", "currency": "numeric",
    "grouped_indian": "numeric", "grouped_international": "numeric", "grouped_european": "numeric",
    "integer": "numeric", "decimal": "numeric", "nan_inf": "invalid_number",
    "date_iso": "date", "date_slash": "date", "date_month_name": "date",
    "boolean": "boolean", "text": "text", "empty": "empty",
}
PLAIN_NUMBER = {"integer", "decimal"}
EXCEL_SERIAL_RANGE = (20000, 80000)      # 1954-10-03 .. 2119-01-10


def classify(values: pd.Series) -> pd.Series:
    """Pattern name for each value. Expects text; blank/whitespace -> 'empty'."""
    s = values.astype("string").fillna("").str.strip()
    conditions = [s.eq("")] + [s.str.fullmatch(rx).fillna(False).astype(bool) for _, rx in PATTERNS]
    choices = ["empty"] + [name for name, _ in PATTERNS]
    return pd.Series(np.select(conditions, choices, default="text"), index=values.index)


def slash_date_parts(values: pd.Series) -> pd.DataFrame:
    """Split d/m/y-like text into three integer parts a, b, year (no meaning assigned yet)."""
    parts = values.astype("string").str.strip().str.extract(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")
    parts.columns = ["a", "b", "year"]
    parts = parts.astype("Int64")
    parts["year"] = parts["year"].where(parts["year"] >= 100, parts["year"] + 2000)
    return parts
