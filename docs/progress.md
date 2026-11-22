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
- 2026-11-21: **Pushed to GitHub** (private, Actions disabled): https://github.com/Hemlata009/InsightFlow
- 2026-11-21: **Review priorities 1–5**: docs/setup corrected, `datetime` type, exact Decimal money maths, standard audit log + plugin traceability, harness hardened (WinError 1455), Phase 1 **frozen** with a reproduced baseline; 442 tests ([discussion 17](discussions/2026-11-21_17_review-priorities.md))
- 2026-11-21: **Business rules BR-1..9 set by InsightFlow**, notes vs warnings, truth check (5/5 PASS on both datasets), chunked fill-from-group; baseline re-recorded → tag `phase1-v1.1`; 449 tests ([discussion 18](discussions/2026-11-21_18_own-business-rules-and-truth-check.md))
- 2026-11-21: **Chaos dataset SALES_003**: 76 problems in one file, every row graded (CSV 81/81, Excel 82/82, chunked 81/81); found and fixed: an invalid value blocked group filling; 453 tests ([discussion 19](discussions/2026-11-21_19_chaos-dataset.md))
- 2026-11-21: **Safe recovery**: chaos set-aside 38% → 13%; repair from formula, partial-date strategies + hook, dateparser, IST, placeholders, overflow, Excel arithmetic; 460 tests ([discussion 20](discussions/2026-11-21_20_recover-set-aside-rows.md))
- 2026-11-22: **Phase 1 closing checks**: header_rows in the rule book, 600k rows 397 s → 82 s, ruff review, pushed; 461 tests; tag `phase1-v1.4` ([discussion 21](discussions/2026-11-22_21_phase1-closing-checks.md))
- 2026-11-22: **Missing-value choices**: fill down/up, guesses marked, BR-9 money guard, business switches checked against limits ([27](discussions/2026-11-22_27_missing-value-choices.md)); rule book layer 4 `configs/choices/` edited from the web page, marks summary in the Run tab; 496 tests ([28](discussions/2026-11-22_28_missing-values-in-ui.md))
- 2026-11-22: **Full Phase 1 re-test** ([30](discussions/2026-11-22_30_phase1-full-retest.md)) and its 4 fixes: giant cells, unclosed quotes, formula-like text, lab partial dates; 510 tests ([31](discussions/2026-11-22_31_retest-fixes.md))

## Current
**Phase 1 finished** (tag `phase1-v1.5`, pushed 2026-11-22). **Phase 2 design started** ([discussion 29](discussions/2026-11-22_29_phase2-start-handover.md)): KPI engine, EDA, charts. Still wanted from the user: one real business file; approval of BR-1..15

## Next
Phase 2: automated analytics, EDA and KPI engine (after the review)
