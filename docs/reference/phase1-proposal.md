# Reference: Original Phase 1 Proposal (from an earlier ChatGPT session)

Saved 2026-11-21 for traceability. **The agreed plan is [../phase1-plan.md](../phase1-plan.md)**, a lean version of this one.

## Scope
Ingestion (files, formats, metadata) → Profiling (types, patterns, quality) → Normalization (dates,
numbers, currencies) → Cleaning (missing, duplicates, rules) → Validation (schema, constraints) →
Audit & Output (reports, logs, quarantine).

Design principle: don't assume every dataset shares the same format, schema, currency, date convention,
missing-value strategy or business rules. Detect, recommend, apply configured rules, validate, and audit.

## Proposed structure (full version)
- `data/`: raw, staging, normalized, processed, quarantine, sample
- `configs/`: default.yaml, sales.yaml, locale.yaml
- `src/insightflow/`:
  - ingestion (file_detector, file_reader, format_converter, metadata)
  - profiling (profiler, type_detector, pattern_detector)
  - normalization (column_names, numeric, currency, datetime, data_types, text)
  - cleaning (missing_values, duplicates, invalid_values, cleaner)
  - schema (schema_inference, schema_registry, schema_validator)
  - rules (business_rules, rule_engine, hooks)
  - pipeline (phase1_pipeline, pipeline_config)
  - reporting (quality_report, cleaning_report)
  - audit (audit_logger, lineage)
- `tests/`, `examples/run_phase1.py`, requirements.txt, pyproject.toml

## Proposed pipeline order
1. File intake: extension, signature, size, empty/corrupt, encoding, delimiter, sheet
2. Extract to a dataframe (CSV, Excel, JSON, JSONL, Parquet) with source metadata
3. Profile before changing data
4. Normalization plan with confidence; flag ambiguous conversions
5. Normalize: names, text, numbers, currency/magnitude, dates/timezones, types
6. Cleaning policies: missing, duplicates, invalid, business rules
7. Validate: schema and rules
8. Split valid rows from quarantined rows (with reasons and source row refs)
9. Write outputs and audit; never overwrite raw

## Output contract
```json
{
  "dataset_id": "SALES_001",
  "status": "completed_with_warnings",
  "source_format": "xlsx",
  "rows_input": 10000, "rows_output": 9850, "rows_quarantined": 150,
  "transformations_applied": [], "validation_errors": [], "warnings": [], "output_paths": {}
}
```
Statuses: completed, completed_with_warnings, needs_review, failed.

## Edge cases
The full list is carried into the test backlog in [../phase1-plan.md](../phase1-plan.md). Items that
were deferred: JSON array vs JSONL, nested JSON, large-file memory, timezone-aware/naive, DST, Unix
timestamps (s/ms/µs), missing year, date strings that are actually IDs, schema changes between versions,
precision-losing conversions.

Key warnings from the proposal:
- 1M INR ≠ 1M USD. Keep currency conversion separate from magnitude parsing.
- Never silently convert an ambiguous date.

## Proposed tools
- Core: Frictionless, Pandas + OpenPyXL, moneyparse (beta), dateparser + dateutil, Pandera, PyJanitor
- Supporting: YData Profiling, Babel, DuckDB, Great Expectations

## Components to build ourselves
Normalization planner, magnitude rules, currency context resolver, date ambiguity resolver, cleaning policy
engine, hook registry, schema registry, audit and lineage, quarantine manager, pipeline orchestrator.

## Review notes (2026-11-21)
- Kept: all principles, the output contract, the statuses, the edge-case list, and wrapping libraries behind our own interfaces.
- Trimmed: ~35 files down to one module per stage; staging/normalized stay in memory; CSV + Excel only.
- Tools deferred: Frictionless (overlaps Pandas + Pandera), PyJanitor (small helpers),
  dateparser (it guesses, which goes against the no-guess rule), profiling/GE/DuckDB/Babel (later phases).
- moneyparse: could not be verified. The link in the proposal pointed to `scrapinghub/price-parser`, a
  different library. Number and currency parsing will be our own, test-first code.
