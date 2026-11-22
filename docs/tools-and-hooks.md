# Tools, GitHub projects and hooks used in Phase 1

Why each one was chosen, what it does for InsightFlow, and what was rejected. Versions: `requirements.txt`,
`web/package-lock.json`. Rule: every third-party tool is wrapped behind InsightFlow's own functions, so a tool can
be replaced later without touching the rest.

## A. Core data tools
| Tool (project) | Version · licence | Why | How it helped |
|---|---|---|---|
| **pandas** (github.com/pandas-dev/pandas) | 3.1.1 · BSD-3 | the standard Python table library | every stage works on pandas tables; vectorized text/number/date operations; `read_fwf` for fixed-width files; `to_datetime` for exact date formats, Excel serials, Unix timestamps |
| **NumPy** (numpy/numpy) | 2.5.5 · BSD-3 | fast arrays under pandas | pattern classification (`np.select`); random generator for reproducible sample data |
| **openpyxl** (foss.heptapod.net/openpyxl) | 3.1.5 · MIT | read/write .xlsx without Excel | read-only streaming of sheets, hidden-sheet detection, merged-cell ranges, formula vs cached value (to find formulas without results), writing the messy Excel test files |
| **pyarrow** (apache/arrow) | 26.0.1 · Apache-2.0 | Parquet files | reads Parquet, and `iter_batches` reads it in pieces for huge files |
| **PyYAML** (yaml/pyyaml) | 6.0.4 · MIT | human-editable rule-book files | all of `configs/` is YAML, so rules change without code |
| **pydantic** (pydantic/pydantic) | 2.14.4 · MIT | validate the rule book | typos (`extra="forbid"`), wrong types, min > max, unknown columns, bad formulas are refused when the config loads |
| **pandera** (unionai-oss/pandera) | 0.36.0 · MIT | table validation | the schema (types, nullable, min/max, allowed values) is generated from the rule book and checks every row, returning the failing row and check |

## B. Tools added to close gaps
| Tool (project) | Version · licence | Gap | How it helped |
|---|---|---|---|
| **DuckDB** (duckdb/duckdb) | 2.0.1 · MIT | files bigger than free RAM | kept rows of each piece are staged in an on-disk DuckDB with a 128 MB cap; window functions find duplicates and key conflicts ACROSS all pieces; `COPY` writes the output. 600k rows in 82 s, peak 446 MB, same result as in-memory |
| **CurrencyConverter** (alexprengere/currencyconverter) | 0.18.23 · Apache-2.0 (data: ECB) | currency conversion | offline European Central Bank rates (42 currencies, INR 2009–Oct 2026); dated conversion with weekend fallback; never invents a rate |
| **dateparser** (scrapinghub/dateparser) | 1.5.1 · BSD-3 | written dates | "5th March 2025", "March 5, 2025", "5 मार्च 2025" (Hindi). Used strictly: dataset languages only, locale day/month order, all parts required, no relative words ("yesterday"), only for values with letters, range-checked |
| **defusedxml** (tiran/defusedxml) | 0.7.1 · PSF | XML files, safely | refuses "XML bombs" (entity expansion) that plain XML parsers accept |
| **tzdata** (python/tzdata) | 2026.6 · Apache-2.0 | time zones on Windows | Asia/Kolkata, America/New_York… for time-zone conversion and daylight saving |

## C. Plugins (hooks)
| Tool (project) | Version · licence | Why |
|---|---|---|
| **pluggy** (pytest-dev/pluggy) | 1.7.0 · MIT | the plugin system behind pytest: proven, tiny, well documented. Lets a business add its own steps without editing the engine |

### The 5 hooks (`src/insightflow/hooks.py`)
| Hook | When it runs | What a plugin can do |
|---|---|---|
| `after_ingest(data, cfg)` | right after reading (all text) | fix a supplier's odd export before anything else |
| `after_normalize(data, cfg)` | after standardizing (typed values) | business-specific corrections |
| `after_clean(data, cfg)` | after cleaning, before the checks | last adjustments |
| `extra_checks(data, cfg)` | with validation | add business checks; each result is `flag` or `quarantine` for a row |
| `resolve_partial_date(column, text, parts, row, record, cfg)` | for "Mar 2025" / "05/03" when `partial_dates` strategy = `plugin` | decide the missing day/year your own way (e.g. the 15th, or the end of the financial quarter) |

### Where the hooks are called (the "sockets" in the line)
```
read file ──► [after_ingest] ──► standardize ──► [after_normalize] ──► complete partial dates ──► [resolve_partial_date]
          ──► clean ──► [after_clean] ──► validate + [extra_checks] ──► repair ──► outputs
```
- In-memory: `pipeline/phase1.py` (`_run`). Chunked (big files): `pipeline/chunked.py`, the same order **per piece**;
  the whole-file pre-passes also apply `after_ingest` / `after_normalize` / `resolve_partial_date`, so group fills and
  spellings match in-memory exactly (test: same output in both modes). In chunked mode a plugin sees one piece at a time.
- `resolve_partial_date` is called from `normalization/partial_dates.py` when `policies.partial_dates` uses `plugin`.
- No dataset has a plugin switched on by default; they are opt-in per dataset (`plugins: [...]`).

### Why hooks
1. **Keep the engine generic:** sales- or company-specific logic lives in a plugin, not in the core
   (the core has a test that forbids domain column names).
2. **Business choices the engine can't know:** e.g. the user's idea for partial dates ("use the 15th", "end of quarter").
3. **Safe extension:** a plugin can't lose rows, every change is logged, and the exact plugin file is fingerprinted.

**Safety rules for plugins:** a plugin may change values but never add, drop or reorder rows; a crash, a bad
result or a row change stops the run with `plugin_error` (nothing half-written); every changed cell is logged
(row, column, old, new); metadata records each plugin's file, SHA-256, version and hooks. Example:
`plugins/sales_sanity.py` flags rows where profit is larger than the sale. Enable per dataset:
`plugins: [plugins.sales_sanity]`.

## D. Web explorer
| Tool | Version · licence | Why / how it helped |
|---|---|---|
| **FastAPI** (fastapi/fastapi) + **uvicorn** | 0.165 / 0.54 · MIT / BSD-3 | small local web API around the same engine (run, profile, tables, change log, edge-case lab); typed requests |
| **python-multipart** | 0.0.34 · Apache-2.0 | file uploads in the API |
| **React** 19, **Vite** 8, **TypeScript** 7 | MIT / MIT / Apache-2.0 | the explorer page; built once and served by FastAPI, so only one light process runs (low-RAM PC) |

## E. Development and safety tools
| Tool | Version · licence | Why / how it helped |
|---|---|---|
| **pytest** (pytest-dev/pytest) | 9.2.0 · MIT | 464 automated tests, including truth, chaos and baseline checks |
| **psutil** (giampaolo/psutil) | 7.2.2 · BSD-3 | the harness measures free RAM and each task's memory and stops tasks before the PC freezes |
| **httpx** | 0.28.1 · BSD-3 | testing the web API |
| **ruff** (astral-sh/ruff) | 0.17.6 · MIT | fast code checker for the code review (unused imports etc.) |
| **SQLite** (built into Python) | — | harness run history without any server |
| **Git + GitHub CLI** | — | version history, private-by-default repo, Actions disabled |

## F. Evaluated and NOT used
| Tool | Why not |
|---|---|
| **pycel** (Excel formula engine) | GPL-3.0 licence could force the whole product to be open source; replaced by our own safe arithmetic evaluator |
| Frictionless, PyJanitor, ydata-profiling, Great Expectations, Babel | overlap with pandas + Pandera + our own code, or not needed yet |
| moneyparse | could not be verified (the link pointed to a different project); our own number parser is tested on every case |
| Docker + PostgreSQL | needs 2–4 GB RAM and WSL; deferred to Phase 9 |
| dateparser for everything | it guesses (missing years, "IST" as Israel, time-zone shifts), so it's used only as a strict fallback |
