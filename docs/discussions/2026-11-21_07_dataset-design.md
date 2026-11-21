# 2026-11-21 · Discussion 07: Milestone 1, combining practice and Superstore data

## Request
"Combine practice and Superstore data." The user approved two datasets, a public Superstore download,
and deferring Docker ("okay do it accordingly, go ahead").

## Options considered
1. Merge both into one file: rejected. Mixing USD and INR, and MDY and DMY dates, in one file is unrealistic and confusing.
2. **Two datasets in the same schema, different locales (chosen).** This proves the engine is general.

## Decisions
- SALES_001 = real Superstore (US). SALES_002 = generated India data with planted stories.
- Both get a messy copy + an Excel copy + an answer key with the same 15 planted issue types (~7% of rows).
- Superstore is downloaded from a public Hugging Face mirror, verified by SHA-256, and kept out of git (licence unclear).
- Different file traits on purpose: cp1252 + comma (001) vs UTF-8-BOM + semicolon (002); headers differ.
- Docker deferred (confirmed).

## Simple explanation
We wrote two exams with answer sheets. One uses real American shop data; the other uses made-up Indian
shop data with rupees and day-first dates. If our cleaning line passes both exams with the same
machine and only a different settings file, we know it's truly general.

## What we found in the real data
Unusual encoding (cp1252), 1 repeated row, 8 repeated order+product pairs, and 438 postal codes that
lost their leading zero. Real data is messy even before we add mistakes.

## Technical explanation
- `scripts/fetch_superstore.py`: urllib download → `.part` file → SHA-256 check → atomic rename. Rejects mismatches.
- `scripts/sample_data/common.py`: `make_messy()` picks distinct rows per issue from a seeded permutation
  (each row gets at most one issue), renders rows in locale-native text, applies a corruption, and records
  it. Duplicates are inserted right after the original. Magnitude text is exact (`1.2345678 L`).
- `india.py`: seeded generator (seed 2002): 400 orders, 1–4 lines each, 200 customers with fixed region/state.
- `superstore.py`: maps 21 columns to the schema, derives Unit_Price, computes natural issues.
- Tests (`tests/sample_data/`): business rules on truth, every answer-key cell matches the messy file,
  duplicates point at copies, Excel header on row 3, byte-identical rebuild, stories present, checksum
  rejection. SALES_001 tests skip if the data isn't fetched.
- Harness fixes found while doing this: relative program paths on Windows; clean failure for a missing
  program; UTF-8 output for child tasks (the ₹ sign crashed the Windows console).
- Test-design lesson: the festive-boost test first grouped by calendar month across two years. Fixed to
  compare per year-month.

## Next steps
Step 2: data dictionary and business rules → `configs/default.yaml`, `configs/sales.yaml`, plus locale
settings for en_US and en_IN.
