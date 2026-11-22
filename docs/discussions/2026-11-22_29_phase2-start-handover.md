# 2026-11-22 · Discussion 29: Starting Phase 2 in a second tab (handover)

## Request
"In this tab I want you to continue with the next phase of this project, so connect with the other Claude tab
so that you can get the context of the project completely."

## What happened
1. Found the other Claude tab (`desktop-a4`) and asked it for a handover.
2. It committed its work first (`c019c8c`: missing-value choices, discussion 28). 496 tests pass, working tree clean.
3. Read `progress.md`, `decisions.md`, `project-overview.md`, `financial-precision.md` and the sales rule book.

## Context handed over (not written anywhere before)
1. **User preference:** choices belong in the **rule book**, and every change also shows up in the **web page**.
   Expect the same for Phase 2: KPI choices in the rule book plus the UI.
2. **Still open:** approval of BR-1..15 (BR-10/11/12 were the user's own decisions); a test on one real business
   file; GitHub repo visibility (the repo is public now; commits after `phase1-v1.4` are local only, push only when asked).
3. **Phase 2 decisions needed from the user:** KPI list, financial year, how returns are counted, report currency.
4. **Working together:** the two tabs say before running tests or `harness ui`, and coordinate before either one edits
   `src/insightflow/config.py` or `src/insightflow/api/app.py`. Phase 1 stays frozen (`tests/test_baseline.py`).

## Already in place for Phase 2
1. Exact money maths: `insightflow.money` (`exact_sum`, `exact_mean`, `exact_ratio`, half-up rounding).
2. Rules for money KPIs in `docs/financial-precision.md` (round once at the end; ratios exact).
3. Clean sales columns: Order_ID, Order_Date, Customer_ID, Product, Category, Sub_Category, Segment, Region, State,
   Quantity, Unit_Price, Sales, Discount, Profit.

## Simple explanation
1. Two helpers are working on the same project. Before the new one starts, the old one explains what's done,
   what's half-done, and which parts not to touch.
2. Like a shift change at a control room: the outgoing operator tells the next one the plant's state first.

## Technical explanation
- Cross-session messages (`ListAgents` / `SendMessage`) between local Claude Code sessions; the peer committed its
  uncommitted diff before the handover, so there's no file clash.
- Single heavy-task rule still holds across both sessions (≈6 GB RAM machine).

## Decision
This tab works on Phase 2 (KPI engine, EDA, charts). Start with a short design conversation with the user.

## Next steps
1. Ask the user what the Phase 2 numbers are for (who reads them, what they decide).
2. Settle the KPI list, financial year, returns and currency, then write the design and plan.
