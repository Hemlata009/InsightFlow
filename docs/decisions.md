# Decision Log

One line per decision. Full reasoning is in the linked discussion file.

| Date | Decision | Discussion |
|---|---|---|
| 2026-11-21 | Start with Sales only, but build a domain-agnostic core with per-domain config files, so other domains can be added later | [01](discussions/2026-11-21_01_sales-vs-generic.md) |
| 2026-11-21 | Agreed mission, vision, outcomes, tools and skills (see project-overview.md) | [02](discussions/2026-11-21_02_project-understanding.md) |
| 2026-11-21 | Core goal: automate the full analytical workflow end to end (trigger -> data -> insights -> delivery) | [02](discussions/2026-11-21_02_project-understanding.md) |
| 2026-11-21 | Every discussion is documented in `docs/` and committed with its step | [03](discussions/2026-11-21_03_documentation-rule.md) |
| 2026-11-21 | Project lives at `Desktop/InsightFlow`, git branch `main`, local commits only (no push until decided) | [03](discussions/2026-11-21_03_documentation-rule.md) |
| 2026-11-21 | Phase 1 uses the lean plan: 10 steps, one module per stage, CSV + Excel only | [04](discussions/2026-11-21_04_phase1-plan.md) |
| 2026-11-21 | Practice data is generated, with planted issues and an answer key | [04](discussions/2026-11-21_04_phase1-plan.md) |
| 2026-11-21 | Default locale India (INR, DD/MM/YYYY, lakh/crore); others configurable | [04](discussions/2026-11-21_04_phase1-plan.md) |
| 2026-11-21 | Phase 1 tools: pandas, numpy, openpyxl, PyYAML, Pydantic, Pandera, pytest; others deferred | [04](discussions/2026-11-21_04_phase1-plan.md) |
| 2026-11-21 | Every dev task runs through the local harness `harness/` (resource guard + watchdog + run history) | [06](discussions/2026-11-21_06_local-harness.md) |
| 2026-11-21 | Local storage is SQLite for now; Docker + PostgreSQL deferred to Phase 9 (5.9 GB RAM, ~0.8 GB free, no WSL) | [06](discussions/2026-11-21_06_local-harness.md) |
| 2026-11-21 | Two sample datasets in one schema: SALES_001 real Superstore (en_US), SALES_002 generated India (en_IN) | [07](discussions/2026-11-21_07_dataset-design.md) |
| 2026-11-21 | Superstore is downloaded (SHA-256 verified) and never committed; SALES_001 outputs are git-ignored | [07](discussions/2026-11-21_07_dataset-design.md) |
| 2026-11-21 | 15 planted issue types (~7% of rows) with an answer key; stories: festive boost, March 2026 North Electronics drop | [07](discussions/2026-11-21_07_dataset-design.md) |
| 2026-11-21 | Rule book = 3 config layers (default → domain → dataset) + locales, validated by Pydantic; typos are errors | [08](discussions/2026-11-21_08_rule-book.md) |
| 2026-11-21 | Sales rules: row = order line; key = Order_ID + Product; discount = fraction ≤ 0.8; returns only if allowed; no currency conversion | [08](discussions/2026-11-21_08_rule-book.md) |
