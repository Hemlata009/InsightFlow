"""Turn number TEXT into numbers, following the dataset locale. Never guesses.

    parse_number("₹1,23,456.00", locale)  -> (123456.0, "currency_symbol_removed+grouping_removed")
    parse_number("1.2345678 L", locale)   -> (123456.78, "magnitude_suffix")
    parse_number("(1,401.97)", locale)    -> (-1401.97, "accounting_negative")
    parse_number("5%", locale)            -> (0.05, "percent")
    parse_number("abc", locale)           -> raises NotConvertible("not_a_number")
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from insightflow.config import LocaleSpec

CURRENCY_SYMBOLS = "₹$€£"
CURRENCY_CODES = ("INR", "USD", "EUR", "GBP")
_GROUP_INDIAN = re.compile(r"^\d{1,2}(,\d{2})*,\d{3}(\.\d+)?$")
_GROUP_INTL = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_PLAIN = re.compile(r"^\d+(\.\d+)?$|^\.\d+$")
_SUFFIX = re.compile(r"^(?P<num>[\d.,]+)\s*(?P<suf>[A-Za-z]+)$")


class NotConvertible(ValueError):
    """The value cannot be converted safely. `reason` is a short code for the log/quarantine."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def parse_number(text: str, locale: LocaleSpec, *, allow_percent: bool = True,
                 allow_magnitude: bool = True, allow_accounting: bool = True) -> tuple[float, str]:
    s = str(text).strip().replace(" ", " ")
    steps: list[str] = []
    if not s:
        raise NotConvertible("empty")
    if s.lower().lstrip("+-") in ("nan", "inf", "infinity"):
        raise NotConvertible("not_finite", s)

    negative = False
    if s.startswith("(") and s.endswith(")"):
        if not allow_accounting:
            raise NotConvertible("accounting_not_allowed", s)
        negative, s = True, s[1:-1].strip()
        steps.append("accounting_negative")
    if s.startswith("-"):
        negative, s = (not negative), s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()

    # currency: symbol or code, before or after the number
    for sym in CURRENCY_SYMBOLS:
        if sym in s:
            if sym != locale.currency_symbol:
                raise NotConvertible("currency_mismatch", f"{sym} in a {locale.currency_code} dataset")
            s = s.replace(sym, "").strip()
            steps.append("currency_symbol_removed")
    for code in CURRENCY_CODES:
        if re.search(rf"(^|\s){code}(\s|$)", s, flags=re.I):
            if code != locale.currency_code:
                raise NotConvertible("currency_mismatch", f"{code} in a {locale.currency_code} dataset")
            s = re.sub(rf"(?i)(^|\s){code}(\s|$)", " ", s).strip()
            steps.append("currency_code_removed")
    if s.startswith("-"):                               # e.g. "₹-500"
        negative, s = (not negative), s[1:].strip()

    multiplier = Decimal(1)
    if s.endswith("%"):
        if not allow_percent:
            raise NotConvertible("percent_not_allowed", text)
        s, multiplier = s[:-1].strip(), Decimal("0.01")
        steps.append("percent")
    else:
        m = _SUFFIX.match(s)
        if m:
            suf = m.group("suf").upper()
            if not allow_magnitude or suf not in locale.magnitudes:
                raise NotConvertible("unknown_suffix", f"{m.group('suf')!r} is not a {locale.description} magnitude")
            s, multiplier = m.group("num"), Decimal(str(locale.magnitudes[suf]))
            steps.append("magnitude_suffix")

    s = s.replace(" ", "")
    if "," in s:
        if locale.thousands_separator != ",":
            raise NotConvertible("unexpected_grouping", text)
        pattern = _GROUP_INDIAN if locale.grouping == "indian" else _GROUP_INTL
        if not (pattern.match(s) or _GROUP_INTL.match(s)):
            raise NotConvertible("bad_grouping", text)   # e.g. 1.234,56 or 12,3
        s = s.replace(",", "")
        steps.append("grouping_removed")
    if not _PLAIN.match(s):
        raise NotConvertible("not_a_number", text)
    try:
        value = Decimal(s) * multiplier
    except InvalidOperation as e:
        raise NotConvertible("not_a_number", text) from e
    value = -value if negative else value
    return float(value), "+".join(steps) or "plain"
