# 2026-11-21 · Discussion 17: Review priorities 1–5 and freezing Phase 1

## Request (5 priorities)
1. Documentation and setup: correct test count, UI description, dependencies, repository visibility.
2. Date versus datetime: preserve time information for future domains.
3. Financial precision: review Decimal handling before KPI calculations.
4. Audit and plugin behaviour: improve transformation traceability.
5. Freeze Phase 1: run the complete local test suite and preserve the verified baseline.

## Done
| # | Result |
|---|---|
| 2 | New column type **`datetime`** keeps the time, converted to the business time zone (`date` unchanged). Locale date-times (`05/03/2025 14:30`), ISO with offsets, Excel serials with fractions and Unix ms keep their time. The date-range rule now includes the whole last day. Output `YYYY-MM-DD HH:MM:SS`. Re-run is idempotent. 12 tests |
| 3 | Review in [../financial-precision.md](../financial-precision.md). Derived values, currency conversion and reporting columns now use **exact Decimal** arithmetic with **half-up** rounding (`round(2.675, 2)` was 2.67; now 2.68). `insightflow.money`: `to_decimal`, `exact_sum`, `exact_mean`, `exact_ratio`, `quantize`, `evaluate` (AST-whitelisted formulas). Proven: every money value in both datasets survives float storage exactly. 16 tests |
| 4 | Every cleaning-log entry has one **standard shape** (`seq, run_id, kind, stage, rule, source_row, column, old, new, severity, detail`), also in chunked mode. Plugin changes are logged **per cell**; metadata records each plugin's file, **SHA-256**, version and hooks. Quality report has an audit summary. New command `python -m insightflow.audit trace <ID> <row>`. UI change log shows `#` and `kind`, filter "plugin". 7 tests |
| 5 | `tests/baseline/phase1_baseline.json` (results + SHA-256 of output files for 3 sample inputs); `tests/test_baseline.py` must reproduce it exactly. Tag `phase1-v1.0`. See [../phase1-baseline.md](../phase1-baseline.md) |
| 1 | README rewritten: correct test count (442), React UI (not Streamlit), setup `pip install -e ".[dev,api]"` + Node.js 20 for the UI, dependency table with licences, repository private + Actions disabled. Stale lines fixed in harness.md and project-overview.md |

## Findings while doing it
1. **NumPy 2 bug:** `repr(np.float64(1.5))` is `"np.float64(1.5)"`, which broke Decimal conversion. Fixed (`repr(float(x))`).
2. **Python 3.12+ `sum()` compensates float error**, so a running total (loop / pandas) is the real risk. Tests now show that.
3. **The PC reached 15 MB free** during one full test run (the tests peaked at 326 MB; the rest was other programs).
4. **The harness watchdog crashed** with `WinError 1455` ("paging file too small") from psutil under that pressure,
   leaving one task briefly unguarded. Fixed: memory errors never crash the guard; an unreadable memory state counts as 0 MB free.
5. Full test runs are now **3 groups in fresh processes**: peak 265 MB, lowest free 348 MB (was 15 MB).

## Simple explanation
We fixed the labels on the box (docs), taught the clock to keep hours and minutes (datetime), made the
cash register count to the exact paisa (Decimal), made the logbook record every single change in the same
format (audit), and finally sealed Phase 1 with a "golden copy" of its results that every future change is
checked against (baseline).
