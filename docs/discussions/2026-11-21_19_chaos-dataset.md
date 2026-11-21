# 2026-11-21 · Discussion 19: A "chaos" dataset with every test case at once

## Request
"Test once on a very unstructured dataset which contains each and every possible test case. Make such a dataset."

## What was built
- `scripts/sample_data/chaos.py` → `data/sample/SALES_003/` (`chaos.csv`, `chaos.xlsx`, `answer_key.json`), config
  `configs/datasets/SALES_003.yaml` (same rules as SALES_002). 76 cases, one per row (multi-row cases for groups,
  duplicates and keys), plus file-level mess. See [../datasets.md](../datasets.md).
- `scripts/check_chaos.py` grades every row (keep + values / flag + rule / quarantine + reason / duplicate);
  `tests/test_chaos.py` enforces it, including chunked mode and byte-identical regeneration.

## Result
| File | Rows graded | As expected | Status |
|---|---|---|---|
| chaos.csv | 81 | **81** | needs_review (31 set aside > 20%) |
| chaos.xlsx | 82 | **82** | needs_review |
| chaos.csv, chunked (pieces of 15 rows) | 81 | **81** | needs_review |

Notes vs warnings worked as designed: title rows, blank rows, sheet choice, hidden sheet, merged cells and extra
columns were **notes**; the nameless column, the duplicated column name, broken rows and uncalculated formulas were **warnings**.

## Findings (first run: 80/81 and 80/82)
1. **Real improvement:** a missing Region in Delhi was NOT filled, because another Delhi row had the invalid region
   "Mars" and the group looked like it disagreed. Group filling now learns only from values that pass the column's
   own rules (allowed values, ranges). One typo can no longer block filling for a whole state. Baselines unchanged.
2. **My expectation was wrong for Excel:** in Excel, a cell starting with `=` IS a formula; saved without a result
   it's correctly set aside as an uncalculated formula (in CSV it stays text). Expectation fixed per file.
3. The minimum chunk size (100 rows) prevented testing chunked mode on small files; lowered to 10.
4. During one full test run the PC fell to **13 MB free** (other programs); the harness then refused to start
   the next test group (219 MB free) instead of risking a freeze. Rerun later: all 453 tests pass.

## Simple explanation
We made the nastiest file we could, with every mistake we know in one place, and wrote down what must
happen to each row. The machine got every single row right, in CSV, in Excel, and in big-file mode. On the
way it showed us one smarter rule to add: a typo in one row shouldn't stop us filling blanks in other rows.
