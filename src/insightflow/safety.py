"""Spreadsheet formula protection (CSV / formula injection, OWASP).

A text cell such as `=HYPERLINK("http://evil.example")` or `@SUM(...)` is run as a formula when the CSV is opened
in Excel / LibreOffice. InsightFlow keeps the value unchanged in its data (it is just text), marks the cell for
review, and writes it to CSV files with a leading apostrophe (`'=HYPERLINK(...)`), so a spreadsheet shows it as
text instead of running it.

Counted as formula-like: text starting with `=`, `@`, a tab or a carriage return, or with `+` / `-` followed by
something containing a letter or "(" (so `+91 98765 43210` and `-20` are left alone).
"""

from __future__ import annotations

import pandas as pd

FORMULA_LIKE = r"^(?:[=@\t\r]|[+\-].*[A-Za-z(])"


def formula_like(values: pd.Series) -> pd.Series:
    """True where a text value would be run as a formula by a spreadsheet."""
    if not (pd.api.types.is_string_dtype(values) or pd.api.types.is_object_dtype(values)):
        return pd.Series(False, index=values.index)
    text = values.astype("string")
    return text.str.contains(FORMULA_LIKE, regex=True, na=False).astype(bool)


def protect_formulas(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of df where formula-like text cells get a leading apostrophe (for CSV files people open)."""
    out = df.copy()
    for c in out.columns:
        mask = formula_like(out[c])
        if mask.any():
            out[c] = out[c].astype("string")
            out.loc[mask, c] = "'" + out.loc[mask, c]
    return out


def unprotect(value):
    """Undo protect_formulas for one value (for code that reads InsightFlow's own CSV outputs)."""
    if isinstance(value, str) and len(value) > 1 and value[0] == "'" and \
            pd.Series([value[1:]]).str.contains(FORMULA_LIKE, regex=True).iloc[0]:
        return value[1:]
    return value
