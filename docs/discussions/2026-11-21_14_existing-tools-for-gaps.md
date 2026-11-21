# 2026-11-21 · Discussion 14: Using existing tools / GitHub projects to close the remaining gaps

## Request
"Use some already existing tools, GitHub repos to cover these requirements/gaps."

## Tool chosen per gap
| Gap | Tool (project) | Licence | How it's used |
|---|---|---|---|
| Files bigger than free RAM | **DuckDB** (github.com/duckdb/duckdb) + Python `csv`, **pyarrow** `iter_batches` | MIT / PSF / Apache-2.0 | Stream pieces of 20,000 rows through the same normalize→clean→validate code; stage kept rows in an on-disk DuckDB (128 MB cap, spills to disk); DuckDB window functions find duplicates and key conflicts **across all pieces** and write the output |
| Currency conversion | **CurrencyConverter** (github.com/alexprengere/currencyconverter) with ECB reference rates | Apache-2.0 (data: ECB) | Offline, dated rates (42 currencies, INR 2009-01-02 … 2026-10-30). Foreign amounts → dataset currency at the row's date; optional reporting-currency columns |
| XML files | **defusedxml** (github.com/tiran/defusedxml) | PSF | Safe parsing; refuses entity-expansion "XML bombs" |
| Fixed-width text | **pandas.read_fwf** | BSD-3 | `colspecs="infer"`; `.fwf`/`.prn`, and `.txt` files with no separator |
| Merged cells, two-row headers | **openpyxl** merged-cell ranges | MIT | Fill each merged block with its top-left value; `header_rows: 2` joins header lines ("Sales" + "Q1" → "Sales Q1") |
| Uncalculated Excel formulas | **openpyxl** (formula vs cached value) | MIT | Detected and those rows set aside with advice. **pycel was evaluated and rejected: GPL-3.0** |
| Add-on steps ("hooks") | **pluggy** (github.com/pytest-dev/pluggy) | MIT | `after_ingest` / `after_normalize` / `after_clean` / `extra_checks`; plugins can't add or drop rows |

## Findings while testing
1. **Chunked mode first gave different results** for 0.5% of product names in SALES_001: the
   "most common spelling" was chosen per piece. Fixed with a whole-file first pass (spelling counts only).
   Chunked output is now **identical** to in-memory output on both datasets (test-enforced).
2. **The memory check refused tiny files** when the PC was busy (free RAM under the 300 MB margin). Now
   files needing less than 20 MB are never refused.
3. **Big uploads were blocked by the 50 MB API limit**, even though chunked mode can handle them. The API
   limit now follows `max_chunked_file_mb` for streamable formats.
4. **Real run on this PC:** 600,000 rows (68 MB) → 42 s, **peak 338 MB**, PC never below 316 MB free.
   In-memory mode would need ~700 MB. Counts matched exactly 16/8/8 per copy of the sample.
5. Test suite peak rose to ~306 MB, and the PC once dipped to 150 MB free during a full run. Chunk
   defaults were lowered to 20,000 rows / 128 MB DuckDB for this PC.

## Decisions
- All new features are **off or automatic-only** by default; no change to current sales results.
- pycel (GPL-3.0) is not used; we may revisit if the user accepts GPL or wants a LibreOffice-based recalculation.
- Chunked mode can't use `fill_from_group` / `impute` (they need the whole table): blanks are kept and flagged, with a warning.
- Plugins aren't run in chunked mode (warning).

## Simple explanation
Instead of building every machine ourselves, we bought proven parts: a warehouse system (DuckDB) so a
huge delivery can be checked box by box, an official exchange-rate table (ECB), a bomb-proof XML opener,
and a standard plug socket (pluggy) for add-ons. One part (pycel) had a licence that would force our whole
product to be open-source, so we didn't buy it.

## Technical explanation
- `pipeline/chunked.py`: `ChunkedRun.sniff()` (normal reader on the first 256 KB), `chunks()` (csv /
  JSONL / pyarrow), `_whole_file_spellings()`, `run_chunked()` (per-piece normalize/clean(dedupe=False)/
  validate → quarantine CSV appended → kept rows `INSERT` into DuckDB `stage` → `row_number()/min() OVER
  (PARTITION BY all value columns)` → duplicates + `count() OVER (PARTITION BY key)` conflicts → `COPY` with BOM).
  Triggered by `policies.large_files: auto|always|never`, `chunk_rows`, `duckdb_memory_mb`, `max_chunked_file_mb`.
- `normalization/currency.py`: `Rates.rate()` with weekend fallback (`max_rate_age_days`), reasons
  `no_exchange_rate` / `rate_too_old` / `rate_not_published_yet`; `add_reporting_columns()`. Config `currency:`
  + column `money: true`.
- `ingestion/reader.py`: `_xml_rows` (defusedxml), `_fwf_rows` (read_fwf), `_fill_merged`, `_mark_uncalculated`,
  `header_rows`, `min_checked_mb`.
- `hooks.py` (pluggy) + `plugins/sales_sanity.py` example; config `plugins: [...]`.
- Tests: `tests/edge_cases/test_gap_*.py` (formats, currency, hooks, large files). Total **401 passing**.
