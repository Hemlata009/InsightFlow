# 2026-11-22 · Discussion 28: Missing-value choices in the rule book AND the web page

## Request
"There should be an option for handling missing values in the rule book (best option according to me)... do each
and every change in the UI too."

## Options considered
1. Edit only the YAML files: works, but not friendly.
2. UI edits the dataset YAML directly: rewriting it would lose its comments and could change other rules.
3. **Chosen:** a 4th rule-book layer `configs/choices/<ID>.yaml`, written by the UI, holding ONLY missing-value
   settings. The rule book stays the single source of truth; the UI is a friendly editor for that part.

## Decisions
1. Rule book tab: **Missing values** editor per column: choice dropdown (set aside, leave blank + mark, fixed
   value, mean/median/mode, fill down, fill up, copy from group, formula, temporary label), with the extra fields
   each one needs (value, method, group columns, "at most N rows away", money permission). Save / back to the
   original rule. Invalid choices are refused with the reason (whole rule book validated before saving).
2. Fixed values are now checked when saved: must be an allowed value and inside min/max.
3. Columns table shows the choice in plain words (+ "your choice" chip); new **Business switches** box shows each
   switch and the limit that enforces it.
4. Run tab: **What was marked for review** (counts by reason, from the change log), e.g. `estimated_value`.
5. Tests ignore saved choices (`tests/conftest.py`), so the frozen baseline is safe; the run fingerprint includes
   the choices file.

## Simple explanation
The rule book now has a fourth page just for blank cells. The web page writes that page for you: pick a choice per
column, press Save. If the choice breaks another rule (for example a value that isn't allowed), it is refused and
you are told why. After a run, the Run tab shows how many values were guessed or marked.

## Technical
`config.py`: `CHOICE_KEYS`, `choices_path`, `read_choices`, `save_choices` (validate via
`load_dataset_config(..., choices=)`, atomic write, empty -> file removed), layer merged last; fill_value check.
`api/app.py`: `GET /api/datasets/{id}/choices`, `PUT /api/datasets/{id}/choices/{column}` (`settings: null` = reset;
400 with readable reason; run lock), `GET /api/runs/{id}/marks`. `phase1._config_fingerprint` + choices file.
UI: `web/src/components/MissingValues.tsx`, `RulesPage.tsx`, `RunPage.tsx`, `api.ts`. Tests: `tests/test_choices.py`.
496 tests passing.

## Next steps
User tries the editor; then Phase 2.
