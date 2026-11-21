# Decision Log

One line per decision. Full reasoning is in the linked discussion file.

| Date | Decision | Discussion |
|---|---|---|
| 2026-11-21 | Start with Sales only, but build a domain-agnostic core with per-domain config files, so other domains can be added later | [01](discussions/2026-11-21_01_sales-vs-generic.md) |
| 2026-11-21 | Agreed mission, vision, outcomes, tools and skills (see project-overview.md) | [02](discussions/2026-11-21_02_project-understanding.md) |
| 2026-11-21 | Core goal: automate the full analytical workflow end to end (trigger -> data -> insights -> delivery) | [02](discussions/2026-11-21_02_project-understanding.md) |
| 2026-11-21 | Every discussion is documented in `docs/` and committed with its step | [03](discussions/2026-11-21_03_documentation-rule.md) |
| 2026-11-21 | Project lives at `Desktop/InsightFlow`, git branch `main`, local commits only (no push until decided) | [03](discussions/2026-11-21_03_documentation-rule.md) |
| 2026-11-21 | Phase 1 uses the lean plan: 10 steps, one module per stage, CSV + Excel only | [04](discussions/2026-11-21_04_phase1-plan.md) |
| 2026-11-21 | Practice data is generated, with planted issues and an answer key | [04](discussions/2026-11-21_04_phase1-plan.md) |
| 2026-11-21 | Default locale India (INR, DD/MM/YYYY, lakh/crore); others configurable | [04](discussions/2026-11-21_04_phase1-plan.md) |
| 2026-11-21 | Phase 1 tools: pandas, numpy, openpyxl, PyYAML, Pydantic, Pandera, pytest; others deferred | [04](discussions/2026-11-21_04_phase1-plan.md) |
| 2026-11-21 | Every dev task runs through the local harness `harness/` (resource guard + watchdog + run history) | [06](discussions/2026-11-21_06_local-harness.md) |
| 2026-11-21 | Local storage is SQLite for now; Docker + PostgreSQL deferred to Phase 9 (5.9 GB RAM, ~0.8 GB free, no WSL) | [06](discussions/2026-11-21_06_local-harness.md) |
| 2026-11-21 | Two sample datasets in one schema: SALES_001 real Superstore (en_US), SALES_002 generated India (en_IN) | [07](discussions/2026-11-21_07_dataset-design.md) |
| 2026-11-21 | Superstore is downloaded (SHA-256 verified) and never committed; SALES_001 outputs are git-ignored | [07](discussions/2026-11-21_07_dataset-design.md) |
| 2026-11-21 | 15 planted issue types (~7% of rows) with an answer key; stories: festive boost, March 2026 North Electronics drop | [07](discussions/2026-11-21_07_dataset-design.md) |
| 2026-11-21 | Rule book = 3 config layers (default → domain → dataset) + locales, validated by Pydantic; typos are errors | [08](discussions/2026-11-21_08_rule-book.md) |
| 2026-11-21 | Sales rules: row = order line; key = Order_ID + Product; discount = fraction ≤ 0.8; returns only if allowed; no currency conversion | [08](discussions/2026-11-21_08_rule-book.md) |
| 2026-11-21 | Reader returns every cell as text + `_source_row`; it never interprets values, renames headers or modifies files | [09](discussions/2026-11-21_09_ingestion.md) |
| 2026-11-21 | Unreadable files fail with stable error codes; rows with the wrong field count are set aside in `bad_rows`, never dropped | [09](discussions/2026-11-21_09_ingestion.md) |
| 2026-11-21 | Max input file 50 MB by default (low-RAM PC); chunked reading deferred | [09](discussions/2026-11-21_09_ingestion.md) |
| 2026-11-21 | Profiler only observes: classifies value patterns and checks them against the rule book; converts nothing | [10](discussions/2026-11-21_10_profiling.md) |
| 2026-11-21 | Derive formulas for missing values live in config (`derive_expression`), validated to columns/numbers/+-*/() only | [11](discussions/2026-11-21_11_phase1-steps5-9.md) |
| 2026-11-21 | No domain column names in core code (enforced by a test); business switches are column min/max in dataset config | [11](discussions/2026-11-21_11_phase1-steps5-9.md) |
| 2026-11-21 | Exact duplicates (after normalization) removed but saved with the row they duplicate; key conflicts only flagged | [11](discussions/2026-11-21_11_phase1-steps5-9.md) |
| 2026-11-21 | Quarantine files keep the ORIGINAL text + reasons; flags count only for kept rows | [11](discussions/2026-11-21_11_phase1-steps5-9.md) |
| 2026-11-21 | Phase 1 complete: ingest → profile → normalize → clean → validate → audit via `run_phase1()` | [11](discussions/2026-11-21_11_phase1-steps5-9.md) |
| 2026-11-21 | UI = React (Vite + TypeScript) + a local FastAPI service, replacing Streamlit; started via `python -m harness ui` | [12](discussions/2026-11-21_12_react-explorer.md) |
| 2026-11-21 | API is local only (127.0.0.1), one run at a time, uploads limited to .csv/.xlsx ≤ max_file_mb | [12](discussions/2026-11-21_12_react-explorer.md) |
| 2026-11-21 | Never run the test suite while the explorer server is running (low RAM) | [12](discussions/2026-11-21_12_react-explorer.md) |
| 2026-11-21 | Low-system-RAM kill needs 5 s of sustained shortage AND a task ≥ 200 MB; a task over its own 1.5 GB limit is still stopped at once | [12](discussions/2026-11-21_12_react-explorer.md) |
| 2026-11-21 | New formats: JSON/JSONL (nested → dotted columns), Parquet, UTF-16 text; files that don't fit in free RAM are refused | [13](discussions/2026-11-21_13_edge-cases.md) |
| 2026-11-21 | `$` means the dataset's own dollar; any other explicit currency is refused; two minus markers are refused | [13](discussions/2026-11-21_13_edge-cases.md) |
| 2026-11-21 | Zoned times are converted to the dataset's business time zone (SALES_002: Asia/Kolkata); Unix/compact dates are opt-in | [13](discussions/2026-11-21_13_edge-cases.md) |
| 2026-11-21 | fill_from_group and impute are available but OFF for sales until the user decides | [13](discussions/2026-11-21_13_edge-cases.md) |
| 2026-11-21 | Outputs are UTF-8 with BOM (Excel-friendly); formula-like cells are reported, not altered | [13](discussions/2026-11-21_13_edge-cases.md) |
