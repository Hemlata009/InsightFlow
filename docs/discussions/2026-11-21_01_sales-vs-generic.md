# 2026-11-21 · Discussion 01: Sales only, or every domain?

## Question
Should InsightFlow be built only for sales, or made general for every business domain?

## Options considered
1. **Sales only, hard-coded:** fastest at first, but adding another domain later means a big rewrite.
2. **Fully general from day one:** means guessing at unknown needs; too big, too slow, nothing works early.
3. **Sales first, designed to be extendable (chosen):** build and finish with sales, and keep every
   sales-specific rule in its own config file.

## Decision
Option 3: **build specific, design general.**

## Simple explanation
Like a multimeter: one tool, a knob to choose what you measure. The inside parts (reading files, finding
missing values, fixing dates, spotting odd numbers) are shared. Only the settings file changes per area.
Example: the sales settings say "sales can't be below zero"; HR settings later say "salary can't be below
zero". The same checker reads a different settings file.

## Technical explanation
- Domain-agnostic core: ingestion, profiling, cleaning functions, validation runner, audit logs.
- Domain pack, e.g. `config/domains/sales.yaml`: schema, business rules, cleaning policy, KPI definitions.
- No domain column names (`Sales`, `Order_ID`) hard-coded in core modules.
- YAGNI: no plugin framework now. Generalize further only when a second domain is added.
- Test of success: adding a second domain (e.g. marketing) should need mostly a new config, not a rewrite.

## Next steps
Phase 1, Milestone 1: select the sales dataset.
