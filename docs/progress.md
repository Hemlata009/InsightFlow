# Progress

## Done
- 2026-11-21: Vision, architecture and Phase 1 roadmap agreed
- 2026-11-21: Decided on sales first with a domain-agnostic design
- 2026-11-21: Project folder, git repo and documentation structure created
- 2026-11-21: Phase 1 lean plan agreed ([phase1-plan.md](phase1-plan.md))
- 2026-11-21: **Phase 1, Step 0: setup** (venv, packages, folders, smoke test, 14 tests passing)
- 2026-11-21: **Local harness** (`harness/`): resource guard, watchdog, SQLite run history (24 tests passing)
- 2026-11-21: **Phase 1, Milestone 1: sample datasets**: SALES_001 (Superstore) + SALES_002 (India), answer keys ([datasets.md](datasets.md)), 49 tests passing
- 2026-11-21: **Phase 1, Step 2: rule book**: layered configs + validated loader ([data-dictionary.md](data-dictionary.md)), 68 tests passing
- 2026-11-21: **Phase 1, Step 3: ingestion**: safe CSV/Excel reader, 9 edge-case checklist items done, 99 tests passing
- 2026-11-21: **Phase 1, Step 4: profiling**: health report finds every planted issue with exact counts, 138 tests passing
- 2026-11-21: **Phase 1, Step 5: normalization**: numbers/dates/text/headers standardized and logged, 190 tests passing
- 2026-11-21: **Phase 1, Step 6: cleaning**: missing-value policies, duplicates, key conflicts, quarantine
- 2026-11-21: **Phase 1, Step 7: validation**: Pandera schema + config rules; finds exactly the planted rule-breakers
- 2026-11-21: **Phase 1, Steps 8–9: audit outputs + full pipeline**: messy files → truth in both datasets, idempotent, 256 tests passing
- 2026-11-21: ✅ **Phase 1 complete** ([discussion 11](discussions/2026-11-21_11_phase1-steps5-9.md))

- 2026-11-21: **React explorer**: Run pipeline / Edge-case lab / Rule book, local FastAPI, 266 tests passing ([discussion 12](discussions/2026-11-21_12_react-explorer.md))
- 2026-11-21: **Edge cases**: 95 new tests in 5 groups; 6 bugs found and fixed; 363 tests passing ([discussion 13](discussions/2026-11-21_13_edge-cases.md))
- 2026-11-21: **Gaps closed with existing tools**: DuckDB chunked mode (600k rows, 338 MB peak), ECB currency conversion, defusedxml, read_fwf, merged cells, pluggy hooks; 401 tests ([discussion 14](discussions/2026-11-21_14_existing-tools-for-gaps.md))

## Current
User explores Phase 1 in the **React explorer** (`python -m harness ui` → http://127.0.0.1:8000), then we review edge cases and requirements

## Next
Phase 2: automated analytics, EDA and KPI engine (after the review)
