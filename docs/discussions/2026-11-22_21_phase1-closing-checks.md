# 2026-11-22 · Discussion 21: Phase 1 closing checks (header rows, speed, code review, GitHub)

## Request
"Yes, do it (#3 two-row headers in the rule book, #4 speed re-check, #5 code review, #7 push to GitHub), then
we'll discuss Phase 2." Also: "turn off the laptop after Phase 1."

## Done
| # | Item | Result |
|---|---|---|
| 3 | Two-row headers | `policies.header_rows` (1–5) in the rule book; works in normal and chunked mode (test) |
| 4 | Speed, 600,000 rows | was **397 s** after the recovery features → **82 s** (peak 446 MB, min free 464 MB); results identical |
| 5 | Code review | `ruff` (MIT) static check: 5 tidy-ups fixed (unused imports, f-string, quoted hints); B008 (FastAPI `File()`) and the DuckDB-read variable are intentional; F/E9 clean |
| 7 | GitHub | pushed `main` and tags to the private repo; Actions still disabled |

## Speed findings (profiled with cProfile on 120k rows)
1. Formula repair validated **one row at a time** with Pandera → now one batch validation per repairable column (397 s → 210 s).
2. **`group_keys`** (key for "same order / same state") joined text row by row in Python: 46 of 75 s →
   vectorized with `str.cat` (210 s → 82 s). Identical keys; baseline, truth and chaos checks unchanged.
3. Remaining cost vs the original 42 s is real work added since: repairs, group filling, partial dates and one
   extra whole-file pass in chunked mode.

## Phase 1 status at close
461 tests passing; frozen baseline reproduced; truth checks 6/6 (SALES_001, SALES_002); chaos 83/83, 84/84,
chunked 83/83 (13% set aside). Open (needs the user): one real business file to test; approval of BR-1..15.
