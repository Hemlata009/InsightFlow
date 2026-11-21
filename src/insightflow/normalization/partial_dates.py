"""Incomplete dates ('Mar 2025' = no day, '05/03' = no year), completed the way the BUSINESS chooses.

Rule book (`policies.partial_dates`):
    missing_day:  first_of_month | last_of_month | fixed_day | median_day | mean_day | mode_day |
                  previous_row | next_row | plugin | quarantine
    missing_year: mode_year | previous_row | next_row | fixed_year | plugin | quarantine
    fixed_day: 15        fixed_year: 2025

  *_day statistics use the complete dates of the SAME month and year in the file (else the whole file).
  previous_row / next_row ("insert up / down") copy from the nearest row above/below with a complete date;
  for a missing day they only copy if that row is in the same month and year (never crosses months).
  plugin: an add-on implementing `resolve_partial_date` (see insightflow.hooks) decides.
Every completed date is logged with its strategy and the row is FLAGGED for a person to check.
Nothing is guessed when the chosen strategy can't answer: the row is set aside as before.
"""

from __future__ import annotations

import calendar
import re
from collections import Counter
from datetime import date

import pandas as pd

from insightflow.ingestion import SOURCE_ROW

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
MONTHS["sept"] = 9


def _month(token: str) -> int | None:
    t = token.strip(". ").lower()
    if t.isdigit():
        v = int(t)
        return v if 1 <= v <= 12 else None
    return MONTHS.get(t)


def _year(token: str) -> int:
    y = int(token)
    return y + 2000 if y < 100 else y


def extract_parts(text: str, date_order: str) -> dict | None:
    """{'month', 'year'} for a missing day; {'day', 'month'} for a missing year; None if not partial."""
    s = str(text).strip()
    for rx in (r"^(?P<m>[A-Za-z]{3,9})\.?[\s\-,]+(?P<y>\d{2,4})$", r"^(?P<m>\d{1,2})[/.\-](?P<y>\d{4})$",
               r"^(?P<y>\d{4})[/.\-](?P<m>\d{1,2})$"):
        m = re.match(rx, s)
        if m and _month(m.group("m")):
            return {"kind": "missing_day", "month": _month(m.group("m")), "year": _year(m.group("y"))}
    m = re.match(r"^(?P<a>\d{1,2})[/.\-](?P<b>\d{1,2})$", s)
    if m:
        a, b = int(m.group("a")), int(m.group("b"))
        day, month = (a, b) if date_order == "DMY" else (b, a)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return {"kind": "missing_year", "day": day, "month": month}
    for rx in (r"^(?P<d>\d{1,2})[\s\-]?(?P<m>[A-Za-z]{3,9})\.?$", r"^(?P<m>[A-Za-z]{3,9})\.?\s+(?P<d>\d{1,2})$"):
        m = re.match(rx, s)
        if m and _month(m.group("m")):
            return {"kind": "missing_year", "day": int(m.group("d")), "month": _month(m.group("m"))}
    return None


class PartialDateContext:
    """What the strategies need from the WHOLE file: date statistics and the nearest complete dates."""

    def __init__(self):
        self.years: Counter = Counter()
        self.days_by_month: dict[tuple[int, int], list[int]] = {}
        self.all_days: list[int] = []
        self.prev: dict[int, pd.Timestamp] = {}
        self.next: dict[int, pd.Timestamp] = {}
        self._last: pd.Timestamp | None = None
        self._waiting: list[int] = []

    def update(self, dates: pd.Series, rows: pd.Series, partial_rows: set[int]) -> None:
        """Feed rows in FILE ORDER (works piece by piece for chunked mode)."""
        for r, d in sorted(zip(rows.astype(int), dates), key=lambda x: x[0]):
            if r in partial_rows:
                if self._last is not None:
                    self.prev[r] = self._last
                self._waiting.append(r)
            elif pd.notna(d):
                d = pd.Timestamp(d)
                self.years[d.year] += 1
                self.days_by_month.setdefault((d.year, d.month), []).append(d.day)
                self.all_days.append(d.day)
                for w in self._waiting:
                    self.next[w] = d
                self._waiting = []
                self._last = d

    @classmethod
    def from_frame(cls, data: pd.DataFrame, column: str, partial_rows: set[int]) -> PartialDateContext:
        ctx = cls()
        ctx.update(data[column], data[SOURCE_ROW], partial_rows)
        return ctx


def _safe_date(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def resolve(parts: dict, policy, ctx: PartialDateContext, row: int, plugin=None, **plugin_args):
    """A date, or None when the chosen strategy can't answer (the row is then set aside)."""
    if parts["kind"] == "missing_day":
        y, m, s = parts["year"], parts["month"], policy.missing_day
        same = ctx.days_by_month.get((y, m)) or ctx.all_days
        if s == "first_of_month":
            return date(y, m, 1)
        if s == "last_of_month":
            return date(y, m, calendar.monthrange(y, m)[1])
        if s == "fixed_day":
            return date(y, m, min(policy.fixed_day, calendar.monthrange(y, m)[1]))
        if s in ("median_day", "mean_day", "mode_day") and same:
            ser = pd.Series(same)
            d = {"median_day": ser.median(), "mean_day": ser.mean(), "mode_day": ser.mode().min()}[s]
            return date(y, m, min(max(1, int(round(d))), calendar.monthrange(y, m)[1]))
        if s in ("previous_row", "next_row"):
            near = (ctx.prev if s == "previous_row" else ctx.next).get(row)
            if near is not None and (near.year, near.month) == (y, m):     # never cross into another month
                return date(y, m, near.day)
            return None
    else:
        d, m, s = parts["day"], parts["month"], policy.missing_year
        if s == "mode_year" and ctx.years:
            return _safe_date(ctx.years.most_common(1)[0][0], m, d)
        if s == "fixed_year" and policy.fixed_year:
            return _safe_date(policy.fixed_year, m, d)
        if s in ("previous_row", "next_row"):
            near = (ctx.prev if s == "previous_row" else ctx.next).get(row)
            return _safe_date(near.year, m, d) if near is not None else None
    if s == "plugin" and plugin is not None:
        out = plugin(parts=parts, row=row, **plugin_args)
        return out.date() if hasattr(out, "date") and callable(out.date) else out
    return None


def resolve_partial_dates(norm, cfg, pm=None, contexts: dict | None = None) -> None:
    """Complete partial dates in place (norm.data / issues / changes / flags), per the rule book."""
    policy = cfg.policies.partial_dates
    todo = [i for i in norm.issues if i["reason"] in ("missing_day", "missing_year")
            and i["column"] in cfg.columns and cfg.columns[i["column"]].type in ("date", "datetime")]
    if not todo:
        return
    plugin = None
    if pm is not None and pm.hook.resolve_partial_date.get_hookimpls():
        plugin = pm.hook.resolve_partial_date
    by_row = dict(zip(norm.data[SOURCE_ROW].astype(int), norm.data.index))
    contexts = contexts or {}
    for col in {i["column"] for i in todo}:
        if col not in contexts:
            partial = {i["source_row"] for i in todo if i["column"] == col}
            contexts[col] = PartialDateContext.from_frame(norm.data, col, partial)
    done = []
    for iss in todo:
        col, row, text = iss["column"], iss["source_row"], iss["value"]
        parts = extract_parts(text, cfg.locale.date_order)
        if parts is None:
            continue
        strategy = policy.missing_day if parts["kind"] == "missing_day" else policy.missing_year
        if strategy == "quarantine":
            continue
        idx = by_row.get(row)
        value = resolve(parts, policy, contexts[col], row, plugin=plugin, column=col, text=text,
                        record=None if idx is None else norm.data.loc[idx].to_dict(), cfg=cfg)
        if value is None or idx is None:
            continue
        norm.data.loc[idx, col] = pd.Timestamp(value)
        norm.changes.append({"stage": "normalize", "rule": f"partial_date:{parts['kind']}:{strategy}",
                             "source_row": row, "column": col, "old": text, "new": pd.Timestamp(value).date().isoformat()})
        norm.flags.append({"stage": "normalize", "flag": f"partial_date_completed:{strategy}", "source_row": row,
                           "column": col, "detail": f"{text!r} completed as {value} ({strategy})"})
        done.append(iss)
    norm.issues[:] = [i for i in norm.issues if i not in done]
