# InsightFlow

**Automated analytical workflow:** raw business data in, trusted insights, reports and recommendations out.

InsightFlow is planned as an MCP-based analytics product. It will ingest business data, check and clean it,
compute KPIs, detect trends and anomalies, investigate root causes, forecast, and deliver reports. Users
will reach it through AI assistants (Claude, ChatGPT), a **React web UI**, and scheduled emails.

- First domain: **Sales analytics** (sample datasets: India / INR, US / USD, and a "chaos" file with one problem per row)
- Design: a **domain-agnostic core** plus **pluggable domain configs** (`configs/`), so new domains can be added

> Repository: **private** (github.com/Hemlata009/InsightFlow). GitHub Actions is **disabled**; all tests run
> locally through the harness.

## Status

**Phase 1 complete and frozen** (tag `phase1-v1.4`): data intake & quality engine.
**486 tests passing** (`python -m harness test -q`: 3 groups). Truth check:
`python -m harness run -- python -m scripts.check_against_truth SALES_002`. Chaos check (every problem in one
file, graded row by row): `python -m harness run -- python -m scripts.check_chaos --chunked`. Verified baseline in
[docs/phase1-baseline.md](docs/phase1-baseline.md). Next: Phase 2 (analytics & KPIs).

Phase 1 covers: CSV / TSV / TXT / Excel / JSON / JSON Lines / Parquet / XML / fixed-width files → profiling →
normalization (Indian / international / European numbers, currencies, dates, date-times, time zones) →
cleaning (missing values, duplicates, quarantine) → validation (schema + business rules) → audit
(cleaned data, quality report, standard change log, metadata). Files bigger than free RAM are processed in
chunks with DuckDB. Optional: ECB currency conversion, plugins (pluggy).

## Documentation

- [Project overview](docs/project-overview.md): mission, vision, outcomes, architecture, tools, skills, phases
- [Phase 1 plan](docs/phase1-plan.md): steps and the edge-case checklist
- [Phase 1 summary](docs/phase1-summary.md): everything done in Phase 1, in one page
- [Tools and hooks](docs/tools-and-hooks.md): every tool/GitHub project used, why, and how it helped
- [Rule book guide](docs/rulebook-guide.md): every rule-book setting, how to change it, examples
- [Phase 1 baseline](docs/phase1-baseline.md): the frozen, verified results
- [Data dictionary & business rules](docs/data-dictionary.md): columns, rules, locales, options
- [Financial precision](docs/financial-precision.md): how money is calculated exactly
- [Sample datasets](docs/datasets.md): SALES_001 + SALES_002, answer keys, how to rebuild
- [Local harness](docs/harness.md): how to run every dev task safely on this PC
- [Decision log](docs/decisions.md) and [discussions](docs/discussions/): every decision with its reasoning
- [Progress](docs/progress.md): where we are now

## Setup (Windows PowerShell)

Needs **Python 3.11+** (developed on 3.14) and, for the web UI, **Node.js 20+** with npm.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,api]"          # engine + tests + web API   (exact versions: requirements.txt)
python -m harness check              # is there enough free memory?
python -m harness test -q            # full test suite, in 3 memory-friendly groups
```
Optional sample data from Tableau's Superstore (not stored in git; its licence is unclear):
```powershell
python -m harness run -- python -m scripts.fetch_superstore
python -m harness run -- python -m scripts.sample_data
```

## Use it

```powershell
# the web UI (React + local API) -> http://127.0.0.1:8000   (Ctrl+C to stop; npm packages install on first run)
python -m harness ui
# the pipeline from the command line
python -m harness run -- python -m insightflow.pipeline data/sample/SALES_002/sales_messy.xlsx SALES_002
# trace everything that happened to one original row
python -m insightflow.audit trace SALES_002 42
```
Web UI tabs: **Run pipeline** (sample or upload; browse clean data, rows set aside, duplicates and the change
log; click a row to trace it), **Edge-case lab** (type any value, see how it's read), **Rule book** (the merged config).

Outputs: `data/processed/<ID>/` (cleaned CSV, quality_report.json, cleaning_log.json, metadata.json) and
`data/quarantine/<ID>/` (rows set aside with their original text and reasons, removed duplicates).

## Dependencies

| Package | Why | Licence |
|---|---|---|
| pandas, numpy | tables and arrays | BSD-3 |
| openpyxl | Excel files | MIT |
| pyarrow | Parquet files | Apache-2.0 |
| PyYAML, pydantic | rule-book files and their validation | MIT |
| pandera | schema validation | MIT |
| duckdb | chunked mode for files bigger than RAM | MIT |
| CurrencyConverter | ECB exchange rates, offline (optional feature) | Apache-2.0 |
| defusedxml | safe XML reading | PSF |
| pluggy | plugins (add-on steps) | MIT |
| tzdata | time-zone data on Windows | Apache-2.0 |
| dateparser | written dates ("5th March 2025", Hindi months) | BSD-3-Clause |
| fastapi, uvicorn, python-multipart *(extra `api`)* | local web API for the UI | MIT / BSD-3 / Apache-2.0 |
| pytest, psutil, httpx *(extra `dev`)* | tests and the local harness | MIT / BSD-3 / BSD-3 |
| React 19, Vite, TypeScript *(web/)* | web UI | MIT / MIT / Apache-2.0 |

Rejected: pycel (GPL-3.0). Exact pinned versions: `requirements.txt` and `web/package-lock.json`.
