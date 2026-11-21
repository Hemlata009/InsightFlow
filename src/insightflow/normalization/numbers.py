"""Turn number TEXT into numbers, following the dataset locale. Never guesses.

    parse_number("₹1,23,456.00", locale)  -> (123456.0, "currency_removed+grouping_removed")
    parse_number("1.2345678 L", locale)   -> (123456.78, "magnitude_suffix")
    parse_number("(1,401.97)", locale)    -> (-1401.97, "accounting_negative")
    parse_number("5%", locale)            -> (0.05, "percent")
    parse_number("1.234,56", de_locale)   -> (1234.56, "grouping_removed")
    parse_number("abc", locale)           -> raises NotConvertible("not_a_number")
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from insightflow.config import LocaleSpec

# Currency markers -> ISO code. "$" alone is resolved by the dataset locale (USD, CAD, AUD... all use it).
CURRENCY_TOKENS = [
    ("US$", "USD"), ("USD", "USD"), ("CA$", "CAD"), ("C$", "CAD"), ("CAD", "CAD"), ("AU$", "AUD"), ("A$", "AUD"),
    ("AUD", "AUD"), ("S$", "SGD"), ("SGD", "SGD"), ("Rs.", "INR"), ("Rs", "INR"), ("INR", "INR"), ("₹", "INR"),
    ("₨", "INR"), ("€", "EUR"), ("EUR", "EUR"), ("£", "GBP"), ("GBP", "GBP"), ("AED", "AED"), ("CHF", "CHF"),
    ("JPY", "JPY"), ("CNY", "CNY"), ("¥", None), ("$", None),     # None = depends on the locale / ambiguous
]
MAX_SIGNIFICANT_DIGITS = 15          # beyond this a float can't hold the value exactly
_MINUS_SIGNS = "−‒–﹣－"   # − ‒ – ﹣ －
_SUFFIX = re.compile(r"^(?P<num>[\d.,]+)\s*(?P<suf>[A-Za-z]+)$")


class NotConvertible(ValueError):
    """The value cannot be converted safely. `reason` is a short code for the log/quarantine."""

    def __init__(self, reason: str, detail: str = "", currency: str | None = None):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.currency = currency          # for currency_mismatch: the ISO code found (None if ambiguous)


def _grouping_patterns(loc: LocaleSpec):
    t, d = re.escape(loc.thousands_separator), re.escape(loc.decimal_separator)
    indian = re.compile(rf"^\d{{1,2}}({t}\d{{2}})*{t}\d{{3}}({d}\d+)?$")
    intl = re.compile(rf"^\d{{1,3}}({t}\d{{3}})+({d}\d+)?$")
    plain = re.compile(rf"^\d+({d}\d+)?$|^{d}\d+$")
    return indian, intl, plain


def _strip_currency(s: str, loc: LocaleSpec, steps: list[str], original: str) -> str:
    for token, code in CURRENCY_TOKENS:
        is_word = token.isalpha() or token.endswith(".")
        pattern = (rf"(?i)(^|(?<=[\s\d]))" + re.escape(token) + r"(?=[\s\d.,]|$)") if is_word else re.escape(token)
        if not re.search(pattern, s):
            continue
        if code is None:                                  # "$" or "¥": only valid if it IS the locale's symbol
            if token != loc.currency_symbol:
                raise NotConvertible("currency_mismatch", f"{token} in a {loc.currency_code} dataset")
        elif code != loc.currency_code:
            raise NotConvertible("currency_mismatch", f"{code} amount in a {loc.currency_code} dataset", currency=code)
        s = re.sub(pattern, " ", s, count=1).strip()
        steps.append("currency_removed")
        break
    return s


def parse_foreign_amount(text: str, locale: LocaleSpec, code: str) -> float:
    """Parse an amount written in another currency (same number style as the dataset)."""
    foreign = locale.model_copy(update={"currency_code": code})
    return parse_number(text, foreign, allow_percent=False)[0]


def parse_number(text: str, locale: LocaleSpec, *, allow_percent: bool = True,
                 allow_magnitude: bool = True, allow_accounting: bool = True) -> tuple[float, str]:
    loc = locale
    s = str(text).strip().replace(" ", " ").replace(" ", " ")
    for m in _MINUS_SIGNS:
        s = s.replace(m, "-")
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
    # Several minus markers ("(500-)", "-(500)", "--500") all mean "negative" in accounting exports:
    # the value is negative (never positive) and the step "double_minus" makes the row FLAGGED for a check.
    if s.endswith("-") and len(s) > 1 and s[-2].isdigit():   # "500-" (accounting/SAP exports)
        if negative:
            steps.append("double_minus")
        negative, s = True, s[:-1].strip()
        steps.append("trailing_minus")
    while s.startswith("-"):
        if negative:
            steps.append("double_minus")
        negative, s = True, s[1:].strip()
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1].strip()
            steps.append("double_minus")
    if s.startswith("(") and s.endswith(")") and negative:      # "(-500)" after a leading minus
        s = s[1:-1].strip()
        steps.append("double_minus")
    elif s.startswith("+"):
        s = s[1:].strip()

    s = _strip_currency(s, loc, steps, text)
    if s.startswith("-"):                                     # e.g. "₹-500"
        if negative:
            steps.append("double_minus")
        negative, s = True, s[1:].strip()

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
            if not allow_magnitude or suf not in loc.magnitudes:
                raise NotConvertible("unknown_suffix", f"{m.group('suf')!r} is not a {loc.description} magnitude")
            s, multiplier = m.group("num"), Decimal(str(loc.magnitudes[suf]))
            steps.append("magnitude_suffix")

    s = s.replace(" ", "")
    indian, intl, plain = _grouping_patterns(loc)
    t, d = loc.thousands_separator, loc.decimal_separator
    if not plain.match(s):
        if t in s and (intl.match(s) or (loc.grouping == "indian" and indian.match(s))):
            s = s.replace(t, "")
            steps.append("grouping_removed")
        elif re.search(r"[.,]", s):
            raise NotConvertible("bad_grouping", f"{text!r} doesn't match {loc.description} number style "
                                                 f"(thousands {t!r}, decimal {d!r})")
        else:
            raise NotConvertible("not_a_number", text)
    if d != ".":
        s = s.replace(d, ".")
    digits = len(s.replace(".", "").lstrip("0"))
    if digits > MAX_SIGNIFICANT_DIGITS:
        raise NotConvertible("precision_loss", f"{digits} significant digits can't be stored exactly")
    try:
        value = Decimal(s) * multiplier
    except InvalidOperation as e:
        raise NotConvertible("not_a_number", text) from e
    value = -value if negative else value
    return float(value), "+".join(steps) or "plain"
