# 2026-11-22 · Discussion 31: Fixing the 4 issues from the full re-test

## Request
"Do it, then we will work on Phase 2" (fix the 4 issues from discussion 30).

## Fixes
| # | Issue | Fix |
|---|---|---|
| 1 | A cell longer than 131,072 characters crashed the run (`_csv.Error`, uncaught in separator detection) | cell limit raised to 10 million characters (`MAX_CELL_CHARS`); detection can't crash; beyond the limit -> clear error `cell_too_large` with the line |
| 2 | One stray `"` swallowed the rest of the file ("no data rows") | `csv_records()`: a line whose quote is not closed on that line and swallows whole rows (closed by a later stray quote, or never) is set aside (`unreadable_row:quote never closed`, original line kept) and reading restarts on the next line; warning names the row. Same in big-file mode. Real multi-line cells, `24" Monitor`, `""` escapes keep working. A quote in the header line -> `corrupt_file` with the reason |
| 3 | Text like `=HYPERLINK(...)` was written as-is (Excel may run it) | value kept unchanged in the data; cell marked `formula_like_text`; CSV outputs (clean, set-aside, duplicates; both modes) write it with a leading `'` so Excel shows text. `insightflow.safety.unprotect()` undoes it for code that reads the outputs (Phase 2!) |
| 4 | Lab showed "Mar 2025" as refused, a run completes it | lab runs the same partial-date policy, using the other typed values as context; shows `partial_date:<kind>:<strategy> (completed and marked)` |

Also found while fixing: big-file mode skipped a bad row placed before the first good row of its sample (fixed:
`first_data_line` counts bad rows too). Separator detection gets a plain-count second try when the quote-aware try
finds nothing (keeps behaviour identical for every file that worked before).

## What counts as formula-like
Text starting with `=`, `@`, tab or carriage return, or `+`/`-` followed by a letter or `(`. Left alone: `-20`,
`+91 98765 43210`, `a=b`.

## Verification
510 tests passing (14 new in `tests/edge_cases/test_gap_retest_fixes.py`); truth checks SALES_002/SALES_001 pass;
chaos 83/83 (csv) and 84/84 (xlsx); frozen baseline unchanged (its cases have no formula-like text); 600k rows:
same results, 91 s (was 80 s; the new quote check plus low free RAM at the time), peak 423 MB.

## Simple explanation
A giant cell no longer breaks the reader. A missing closing quote now costs only its own row, not the rest of the
file. Text that Excel would run as a formula is kept, marked, and written so Excel shows it as plain text. The
try-out lab now gives the same answer as a real run for incomplete dates.

## Next steps
Phase 2 (in the other tab). Note for Phase 2: read InsightFlow's CSV outputs with `unprotect()` for text columns.
