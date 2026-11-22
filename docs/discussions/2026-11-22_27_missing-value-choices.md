# 2026-11-22 · Discussion 27: Missing-value choices for the user + the business-switch weak spot

## Questions
1. Fix the weak spot: `business.returns_allowed` was not read by the engine (approved: "work on").
2. "While handling missing values some options should be given to the user: mean/median/mode, a fixed value,
   fill up, fill down, NA, 0, or the user can write… should we handle it now or in Phase 2?"

## Options considered
- Now (Phase 1) vs Phase 2. Missing values are part of cleaning = Phase 1's job; Phase 2 (KPIs) needs them done.
- Most choices already existed: quarantine, keep blank (NA) + mark, fixed value (0 / any text), derive, copy from
  group, mean/median/mode, placeholder, plugins. Missing: fill down, fill up.
- Point-and-click choice in the web page: bigger UI work; the rule book is already the user's place to choose.

## Decisions
1. **Now, in Phase 1:** added `fill_down` / `fill_up` (original file order; optional `group_by`; optional
   `fill_limit`); each fill logged with the row it came from and marked `estimated_value`.
2. **Every guessed value is marked** (impute too), so a person can review guesses.
3. **BR-9 enforced:** guessing a money amount (impute/fill_down/fill_up on `money: true`) is refused unless the
   column says `allow_estimates: true`. Fixed values (e.g. 0) are allowed.
4. **Business switches checked:** `returns_column` / `profit_column`; the loader refuses disagreement with `min`.
5. Big-file mode: impute / fill_down / fill_up fall back to keep + mark with a warning (known limit).
6. Choosing in the web page: proposed for later (needs the user's go-ahead).

## Simple explanation
Blank cells now have a full menu: set aside, leave blank, put 0 or your own word, average/middle/most common,
copy from the row above or below, copy from the same group, or work it out. Guesses are always written down and
marked. For money, guessing must be switched on on purpose. And the "returns allowed" switch can no longer say
something different from the real limit: the rule book is refused if they disagree.

## Technical
`config.py`: `MissingPolicy` + fill_down/fill_up, `ESTIMATING_POLICIES`, `ColumnSpec.fill_limit` (ge=1),
`allow_estimates`, `Business.returns_column/profit_column` + `DatasetConfig` cross-check. `cleaner.py`:
`_fill_nearby` (sort by SOURCE_ROW, `ffill`/`bfill` with `limit`, groupby `group_keys` for groups, provenance via
a parallel SOURCE_ROW series), `_estimated`. `chunked.py`: fallback per policy. Tests:
`tests/edge_cases/test_gap_missing_choices.py` (19). 486 tests passing; baseline unchanged.

## Next steps
User: web-page picker for missing values now or in the UI phase? Then Phase 2.
