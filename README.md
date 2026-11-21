# InsightFlow

**Automated analytical workflow:** raw business data in, trusted insights, reports and recommendations out.

InsightFlow is an MCP-based analytics product. It ingests business data, checks and cleans it, computes
KPIs, detects trends and anomalies, investigates root causes, forecasts, and delivers reports
automatically. Users can reach it through AI assistants (Claude, ChatGPT), a Streamlit UI, or scheduled emails.

- First domain: **Sales analytics**
- Design: a **domain-agnostic core** plus **pluggable domain configs**, so new domains can be added later

## Documentation

- [Project overview](docs/project-overview.md): mission, vision, outcomes, architecture, tools, skills, phases
- [Decision log](docs/decisions.md): every decision, one line each
- [Discussions](docs/discussions/): one file per discussion, with the full reasoning
- [Phase 1 plan](docs/phase1-plan.md): steps and the edge-case test backlog
- [Data dictionary & business rules](docs/data-dictionary.md): columns, rules, locales
- [Sample datasets](docs/datasets.md): SALES_001 + SALES_002, answer keys, how to rebuild
- [Local harness](docs/harness.md): how to run every dev task safely on this PC
- [Progress](docs/progress.md): where we are now

## Status

Phase 1: setup, local harness and Milestone 1 (sample datasets) and Step 2 (rule book) done. Next: Step 3, ingestion.

> Run every dev task through the harness. See [CLAUDE.md](CLAUDE.md) and [docs/harness.md](docs/harness.md).

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m harness check
python -m harness test -q
```
