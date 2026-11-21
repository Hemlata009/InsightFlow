# Phase 1 baseline (frozen 2026-11-21; current tag `phase1-v1.1`)

The behaviour of Phase 1 is frozen by `tests/baseline/phase1_baseline.json`, recorded with
`python -m scripts.make_baseline`. `tests/test_baseline.py` re-runs the pipeline on each sample file and
requires **identical** results and **identical output files** (SHA-256 of cleaned, quarantine and duplicates
files). Any change to Phase 1 behaviour therefore shows up as a failing test. If the change is deliberate,
re-record the baseline and explain why in the commit.

## Verified results
| Input | Rows in | Clean out | Set aside | Duplicates removed | Flagged | Status |
|---|---|---|---|---|---|---|
| SALES_002 `sales_messy.csv` (India, generated) | 1,013 | 989 | 16 | 8 | 0 | completed_with_warnings |
| SALES_002 `sales_messy.xlsx` (same data, Excel, header on row 3) | 1,013 | 989 | 16 | 8 | 0 | completed_with_warnings |
| SALES_001 `sales_messy.csv` (US, real Superstore) | 10,074 | 9,833 | 160 | 81 | 20 | completed_with_warnings |

"Completed with warnings" here = the planted bad rows were set aside (correct). A clean file gives `completed`:
the truth file and a re-run of the cleaned output both do (SALES_002).

**v1.1 (re-recorded on purpose):** business rules BR-2/3/4 fill blanks from the same state/order
(SALES_002: 8 → 0 flagged; SALES_001: 92 → 20, of which 16 are real repeated order+product keys);
ISO dates are no longer logged as changes; harmless messages are *notes*, not warnings.

## Truth check (run any time)
`python -m harness run -- python -m scripts.check_against_truth SALES_002` (and SALES_001): 5 checks, all PASS:
every cleaned value equals the truth; set-aside rows = planted bad rows; duplicates = planted + natural;
re-running the cleaned output changes nothing; the truth file passes (only proven spacing fixes).

"Set aside" = exactly the rows the answer key planted as bad. Clean data = the truth file (numbers within 0.001).

## Test suite at freeze
**447 tests passing**, run as 3 groups in fresh processes (`python -m harness test -q`):
| Group | Tests | Peak RAM |
|---|---|---|
| tests/harness | 20 | 150 MB |
| tests/edge_cases | 146 | 230 MB |
| all other tests | 281 | 267 MB |

## Environment at freeze
Windows 11, Python 3.14.4; pinned packages in `requirements.txt` (pandas 3.1.1, numpy 2.5.5, pandera 0.36.0,
pydantic 2.14.4, duckdb 2.0.1, pyarrow 26.0.1, …); web UI: React 19 / Vite 8 / TypeScript (see `web/package-lock.json`).
