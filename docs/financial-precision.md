# Financial precision: review and rules (before Phase 2 KPIs)

Reviewed 2026-11-21. Code: `src/insightflow/money.py`. Tests: `tests/test_money.py`.

## Findings
| Where | Before | Risk | Now |
|---|---|---|---|
| Reading text → number | `Decimal` parse, then stored as float64 | None: values have ≤ 15 significant digits (guard), so `repr(float)` gives back the exact text | unchanged; **proven for every money value** in both datasets |
| Derived missing values (`derive_expression`) | float `eval` + float `round()` | `round(2.675, 2) = 2.67`; `0.1*3 = 0.30000000000000004` | exact `Decimal` formula evaluation (`money.evaluate`, AST-whitelisted) + **half-up** rounding |
| Currency conversion | float × float, `round(…, 4)` | tiny binary error before rounding | `Decimal(amount) × Decimal(rate)`, half-up to 4 decimals |
| Reporting currency columns | float × float, `.round(4)` | same | exact per value |
| Formula check (validation) | float with tolerance 0.01 + 0.1% | none (it's a tolerance check) | unchanged |
| Adding up (Phase 2) | not built yet | running float totals drift (0.1 ten times = 0.9999999999999999) | `exact_sum`, `exact_mean`, `exact_ratio` ready |
| NumPy 2 | — | `repr(np.float64(1.5))` is `"np.float64(1.5)"`, which broke Decimal conversion | fixed: `repr(float(x))` (bug found by the tests) |

## Rules for Phase 2 (KPI engine)
1. **Store** amounts as float64 (lossless for ≤ 15 significant digits; fast for pandas).
2. **Calculate** money KPIs in `Decimal` via `insightflow.money` (`exact_sum`, `exact_ratio`, …), never with running float totals.
3. **Round once, at the end**, to the currency's minor units (`minor_units("INR") = 2`, JPY = 0), **half-up**.
4. Ratios (margin %, growth %) are computed exactly and rounded only for display.
5. Totals in reports must equal the sum of the rounded line items, or show a rounding note (to be decided with the user).

## Simple explanation
Computers store most decimal numbers as tiny approximations, like 0.1 being stored as 0.1000000000000000055…
Storing is fine here, because we can always get the exact typed value back. Doing maths on the approximations
slowly adds errors, though, and money must add up to the paisa. So all money maths now uses exact decimal
arithmetic, and rounding is ordinary school rounding (2.675 → 2.68).
