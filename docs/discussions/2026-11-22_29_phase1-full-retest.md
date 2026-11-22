# 2026-11-22 · Discussion 29: Full Phase 1 re-test

## Request
"Re-test Phase 1 completely; if not satisfied, tell me the key points. Can I start Phase 2 in another tab?"

## Answer on the second tab
Yes, with rules: one heavy task (tests, pipeline runs, build, `harness ui`) at a time across ALL tabs; the Phase 2
tab adds new files and does not change Phase 1 code while Phase 1 is being tested; each tab commits only its own
files. The Phase 2 tab (insightflow-19) was asked to hold heavy work during the re-test and agreed.

## What was re-tested (all through the harness)
| Check | Result |
|---|---|
| Full test suite (3 groups, incl. frozen baseline) | 496 passed, 0 skipped |
| Truth check SALES_002 / SALES_001 | 6/6 PASS each (997 / 9,953 rows) |
| Chaos check | ALL PASS (Excel 84/84, 13.1% set aside) |
| Pipeline on every sample (csv + xlsx, 3 datasets, truth file) | CSV = Excel results; truth file: completed, 0 set aside |
| Big file 600,000 rows (chunked) | 80.5 s, peak 442 MB, 0.8% set aside (same share as the small file) |
| 14 new strange-input probes | 12 handled correctly; 1 crash, 1 misleading message (below) |
| Saved web-page choices on the real messy file | used correctly |
| Web build (type check) + live API (run, marks, log, lab) | pass |
| Code check | no real errors; 48 style remarks |

## Key points (not satisfied)
1. **Crash:** a single cell longer than 131,072 characters stops the run with an unhandled `_csv.Error`.
2. **Unclosed quote:** one stray `"` swallows the rest of the file; the message says "header but no data rows"
   and the valid rows after it are lost.
3. **Spreadsheet formula injection:** text starting with `=`, `+`, `-`, `@` (e.g. `=HYPERLINK(...)`) is written
   unchanged to the cleaned CSV; opening it in Excel could run it. Not detected or neutralized.
4. **Lab vs run:** the lab shows "Mar 2025" / "05/03" as refused; a run completes them (partial-date policy).
5. Known limits: big-file mode can't use impute / fill down / fill up (falls back to keep + mark); plugins see one
   piece at a time; Excel functions (SUM…) not calculated; very large Excel files can't use chunked mode.
6. Not yet done: a real business file; user approval of BR-1..15; automated tests of the web page itself.

## Recommendation
Fix 1–4 before Phase 2 (small, one step); keep 5 as documented limits; 6 needs the user.

## Simple explanation
Almost everything passed again: the answer sheets, the chaos file, the huge file, every sample, and the web page.
The new strange files found two ways to break the reader (a giant cell, a missing closing quote), one safety gap
(text that Excel would run as a formula), and one place where the try-out lab tells a different story from a real run.
