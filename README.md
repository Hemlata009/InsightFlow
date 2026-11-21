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
- [Progress](docs/progress.md): where we are now

## Status

Phase 1, Step 0 (setup) done. Next: Step 1, generate practice sales data.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```
