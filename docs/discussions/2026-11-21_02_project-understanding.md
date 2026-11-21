# 2026-11-21 · Discussion 02: Project understanding and core goal

## Question
What are InsightFlow's mission, vision, outcomes, tools and skills? (Confirmed by the user.)
The user also stated the core goal: **"I want to automate the analytical workflow."**

## Decision
- Mission, vision, outcomes, tools and skills are recorded in [project-overview.md](../project-overview.md).
- Core goal: **automate the whole analytical workflow end to end.**

## Simple explanation
Today a person does every step by hand: open the file, fix mistakes, work out totals, make charts, write
a summary, email it. InsightFlow does all of it in one go, like an automatic production line: raw
material goes in one end, and a finished, checked product comes out the other. You only press start, or
set a timer so it starts on its own.

Example: every Monday at 9 am it picks up last week's sales file, checks it, works out the totals, spots
the region that dropped, explains why, and emails the manager.

## Technical explanation
- Pipeline: Ingest -> Profile -> Clean -> Validate -> KPIs/EDA -> Anomaly/RCA -> Forecast/Recommend -> Report -> Email.
- Triggers: manual run, file upload (Streamlit), MCP tool call from an AI client, or a schedule (APScheduler).
- Each stage is a separate, testable module with clear inputs and outputs, so stages can be chained
  automatically (later by a plain pipeline runner, then by LangGraph for AI-driven steps).
- Deterministic stages (Python/SQL) produce the numbers; the LLM only interprets those results.
- Automation is built up phase by phase. Phase 1 automates the data-quality part first.

## Next steps
Create the project and document the discussions (done), then start Milestone 1: dataset selection.
