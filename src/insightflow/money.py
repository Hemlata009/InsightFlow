"""Exact money arithmetic (Python's decimal module) for derivations, conversions and, from Phase 2, KPIs.

Why: binary floats can't hold most decimal fractions exactly. 0.1 + 0.2 = 0.30000000000000004, and
round(2.675, 2) = 2.67 (not 2.68). Storage as float is still safe for us, because every number we accept
has at most 15 significant digits (see normalization.numbers.MAX_SIGNIFICANT_DIGITS). Such a float
always prints back to the exact text it came from, so `to_decimal()` recovers the exact value.
Rule: **calculate in Decimal, round once at the end, half-up.**

    to_decimal(0.1)                        -> Decimal('0.1')
    exact_sum([0.1] * 10)                  -> Decimal('1.0')       (float sum: 0.9999999999999999)
    quantize(Decimal("2.675"), 2)          -> Decimal('2.68')
    evaluate("Quantity * Unit_Price * (1 - Discount)", {...})   -> exact Decimal
"""

from __future__ import annotations

import ast
import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

# ISO 4217 minor units (digits after the decimal point) for currencies we may meet
MINOR_UNITS = {"INR": 2, "USD": 2, "EUR": 2, "GBP": 2, "CAD": 2, "AUD": 2, "SGD": 2, "AED": 2, "CHF": 2,
               "CNY": 2, "JPY": 0, "KRW": 0}
PRECISION = 34     # decimal digits used for intermediate results (IEEE decimal128)


def to_decimal(value) -> Decimal | None:
    """float/int/str -> exact Decimal. Floats use their shortest round-trip text (what was typed)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return Decimal(repr(float(value)))      # float(): numpy 2 prints np.float64(1.5) as its repr
    try:
        if hasattr(value, "item"):                 # numpy / pandas scalar
            return to_decimal(value.item())
        import pandas as pd
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def quantize(value: Decimal, places: int) -> Decimal:
    """Round half-up ('school rounding') to `places` decimals: 2.675 -> 2.68, -2.675 -> -2.68."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def minor_units(currency_code: str) -> int:
    return MINOR_UNITS.get(currency_code, 2)


def exact_sum(values) -> Decimal:
    """Sum without float drift. Missing values are skipped (like pandas' sum)."""
    total = Decimal(0)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for v in values:
            d = to_decimal(v)
            if d is not None:
                total += d
    return total


def exact_mean(values) -> Decimal | None:
    ds = [d for d in (to_decimal(v) for v in values) if d is not None]
    if not ds:
        return None
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return sum(ds, Decimal(0)) / len(ds)


def exact_ratio(numerator, denominator) -> Decimal | None:
    """e.g. margin = profit / sales, None when the denominator is 0 or missing."""
    n, d = to_decimal(numerator), to_decimal(denominator)
    if n is None or d is None or d == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return n / d


_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd,
            ast.Name, ast.Load, ast.Constant)


def evaluate(expression: str, values: dict) -> Decimal | None:
    """Evaluate a config formula (columns, numbers, + - * / and brackets) exactly. None if a value is
    missing or the result is undefined (division by zero). Anything else in the formula is refused."""
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ValueError(f"not allowed in a formula: {type(node).__name__}")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            d = to_decimal(values.get(node.id))
            if d is None:
                raise _Missing
            return d
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        a, b = ev(node.left), ev(node.right)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if b == 0:
            raise _Missing
        return a / b

    with localcontext() as ctx:
        ctx.prec = PRECISION
        try:
            return ev(tree)
        except _Missing:
            return None


class _Missing(Exception):
    pass
