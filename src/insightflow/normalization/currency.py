"""Dated currency conversion using the European Central Bank reference rates.

Tool: CurrencyConverter (github.com/alexprengere/currencyconverter, Apache-2.0). It ships the ECB's
historical rates inside the package, so it works offline. Other currencies are converted through EUR
cross rates (ECB method). Weekends/holidays have no rate: the last rate up to `max_rate_age_days`
earlier is used; anything older is refused, never guessed.

    rates = Rates(max_age_days=7)
    rate, rate_day = rates.rate("USD", "INR", date(2025, 3, 8))   # Saturday -> Friday's rate
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from .numbers import NotConvertible


@lru_cache(maxsize=1)
def _converter():
    from currency_converter import CurrencyConverter
    return CurrencyConverter(fallback_on_missing_rate=False, fallback_on_wrong_date=False)


class Rates:
    source = "ECB euro foreign exchange reference rates (bundled with CurrencyConverter)"

    def __init__(self, max_age_days: int = 7):
        self.max_age_days = max_age_days
        self._cache: dict[tuple, tuple[float, date]] = {}

    @property
    def currencies(self) -> set[str]:
        return set(_converter().currencies)

    def bounds(self, code: str) -> tuple[date, date] | None:
        b = _converter().bounds.get(code)
        return (b.first_date, b.last_date) if b else None

    def rate(self, frm: str, to: str, day: date) -> tuple[float, date]:
        """Units of `to` per 1 `frm` on `day` (or the last earlier rate within max_age_days)."""
        if frm == to:
            return 1.0, day
        key = (frm, to, day)
        if key in self._cache:
            return self._cache[key]
        cc = _converter()
        for code in (frm, to):
            if code not in cc.currencies:
                raise NotConvertible("no_exchange_rate", f"the ECB publishes no rate for {code}")
        from currency_converter import RateNotFoundError
        for back in range(self.max_age_days + 1):
            d = day - timedelta(days=back)
            try:
                r = float(cc.convert(1, frm, to, date=d))
            except RateNotFoundError:
                continue
            self._cache[key] = (r, d)
            return r, d
        ends = [b[1] for b in (self.bounds(frm), self.bounds(to)) if b]
        last = min(ends) if ends else day
        if day > last:
            raise NotConvertible("rate_not_published_yet", f"ECB rates in this package end on {last}")
        raise NotConvertible("rate_too_old", f"no {frm}->{to} rate within {self.max_age_days} days before {day}")


def add_reporting_columns(df, cfg):
    """Add <money column>_<CODE> copies converted at each row's date. Originals are never changed.
    Returns (frame, info) where info counts converted rows and rows without a rate."""
    import pandas as pd

    target = cfg.currency.reporting_currency
    if not target:
        return df, {}
    rates = Rates(cfg.currency.max_rate_age_days)
    src = cfg.locale.currency_code
    days = df[cfg.currency.rate_date_column]
    per_day: dict = {}
    failures: dict[str, int] = {}
    for d in days.dropna().dt.date.unique():
        try:
            per_day[d] = rates.rate(src, target, d)[0]
        except NotConvertible as e:
            failures[e.reason] = failures.get(e.reason, 0) + 1
    factor = days.dt.date.map(per_day).astype("Float64")
    out = df.copy()
    money = [c for c, s in cfg.columns.items() if s.money and c in df]
    for c in money:
        out[f"{c}_{target}"] = (out[c].astype("Float64") * factor).round(4)
    info = {"reporting_currency": target, "from": src, "columns": [f"{c}_{target}" for c in money],
            "rows_converted": int(factor.notna().sum()), "rows_without_rate": int(factor.isna().sum()),
            "dates_without_rate": failures, "rate_source": Rates.source}
    return out, info
