# 2026-11-21 · Discussion 18: InsightFlow's own business rules, notes vs warnings, truth check

## Request
"Right now I don't have any business rules, so make your own business rules. Test a cleaned file so we can
check whether it's working correctly. Do #3 (notes vs warnings) yourself."

## 1. Business rules (BR-1..9), see [../data-dictionary.md](../data-dictionary.md)
Facts checked first, in both datasets: every state → exactly one region (14/14 and 49/49); every order → one
customer and one date; 76% / 49% of orders have several lines. Hence:
- **BR-2** missing Region ← same State · **BR-3** missing Customer_ID ← same order · **BR-4** missing Order_Date ← same
  order (else set aside) · **BR-5** disagreement → never copy. The rest keeps the earlier defaults.
- Mechanism: `missing_policy: fill_from_group` (already built); a non-nullable column with nothing to copy is now set aside.

## 2. Notes vs warnings
`pipeline/messages.py`: information (sheet chosen, header row, blank rows skipped, repeated upload, unknown
extra column, chunked mode…) → `result.notes`, shown greyed out in the UI. Only warnings, set-aside rows and flags
make a run "completed_with_warnings". Unknown messages default to warnings (safe).

## 3. Truth check (`scripts/check_against_truth.py`, also a test)
| Check | SALES_002 | SALES_001 |
|---|---|---|
| 1. every cleaned value = truth | PASS (989 rows × 14 columns; **12/12 planted blanks filled correctly**) | PASS (9,833 rows; **112 blanks filled**) |
| 2. set-aside = planted bad rows | PASS (16 = 16) | PASS (160 = 160) |
| 3. duplicates = planted + natural | PASS (8) | PASS (80 + 1) |
| 4. cleaned output re-run changes nothing | PASS, status **completed** | PASS (20 flags = real data issues) |
| 5. truth file passes | PASS, status **completed** | PASS (273 proven spacing-only fixes: invisible non-breaking spaces) |

## Findings
1. Re-running a cleaned file logged every ISO date as a "change" (same date, different text). ISO is our canonical
   output, so it's no longer logged. Mixed date styles are still reported by the health check.
2. **Chunked mode would have given different results** with the new rules (it couldn't see other pieces). Added
   a whole-file pass that learns each group's value; chunked output is again identical to in-memory (tests).
3. SALES_001's truth (real data) contains invisible non-breaking spaces; the check now accepts **only proven
   spacing-only** changes there and fails on anything else.

## Simple explanation
I wrote the shop's house rules myself, based on what the data shows (a state is always in one region, an order
always has one customer and one date). Then I gave the machine the exam again: every cleaned value matched the
answer sheet, every planted mistake was caught, and a clean file now comes out as plain "Completed".
