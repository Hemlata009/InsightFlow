# 2026-11-22 · Discussion 26: Everything about the rule book

## Question
"Now I want to know everything about the rule book."

## Answer
Full guide: [../rulebook-guide.md](../rulebook-guide.md): files and layers, every policy, the sales data
dictionary, rule kinds, duplicates, datasets, country styles, BR-1…15, partial-date strategies, the safety checks
on the rule book itself, how to change rules (examples), and how to add a new data area.

## Finding while answering
`business.returns_allowed` / `negative_profit_allowed` are not read by the engine (documentation only); the real
switch is the column range. Nothing warns if they disagree. Proposed: the loader checks that they agree.

## Next steps
User decides whether to fix the weak spot; then Phase 2.
