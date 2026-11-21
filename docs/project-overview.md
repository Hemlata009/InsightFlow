# InsightFlow: Project Overview

## Core goal

**Automate the full analytical workflow.** One trigger (a file upload, a schedule, or a question from an AI
assistant) runs the whole chain with no manual steps:

```
Data sources -> Ingest -> Profile -> Clean -> Validate -> KPIs/EDA -> Insights/Anomalies/RCA
            -> Forecasts/Recommendations -> Dashboards/Reports -> Email to stakeholders
```

## Mission

1. Take a company's raw data (CSV, Excel, SQL, APIs).
2. Check and clean it carefully, and never modify the raw source.
3. Compute KPIs, trends and anomalies with deterministic code.
4. Explain what happened, why, and what to do next.
5. Deliver results automatically to the right stakeholders.

## Vision

A business user asks "Why did sales drop in the North last month?" and gets a correct, evidence-backed
answer through a chat assistant, a dashboard or an email, without needing a data analyst.
**Numbers come from code; the AI only interprets and recommends. It never invents numbers.**

## Architecture principles

- Python/SQL: deterministic calculations, cleaning, KPIs, statistics.
- ML: forecasting, prediction, anomaly detection.
- LLMs: interpret evidence, explain findings, recommend actions.
- LangGraph: orchestrates multi-step AI investigations.
- MCP: the *interface* for AI clients, not the analytics engine.
- React (Vite + TypeScript) + local FastAPI: visual UI (replaced Streamlit on 2026-11-21).
- APScheduler / worker: scheduled workflows that run without an AI client open.
- **Domain-agnostic core + domain config packs** (e.g. `config/domains/sales.yaml`). Nothing
  domain-specific is hard-coded in core modules.

## Outcomes

| # | Outcome | Phase |
|---|---|---|
| 1 | Reliable data-quality pipeline with an audit trail | 1 |
| 2 | Automated KPIs, EDA, charts | 2 |
| 3 | Anomaly detection and root-cause analysis | 3 |
| 4 | Forecasting and predictive analytics | 4 |
| 5 | LangGraph multi-step AI workflows | 5 |
| 6 | MCP server for Claude / ChatGPT | 6 |
| 7 | React dashboard (explorer started early, in Phase 1) | 7 |
| 8 | HTML/PDF reports and email automation | 8 |
| 9 | Database, scheduling, monitoring, production readiness | 9 |

## Tools (introduced only when a phase needs them)

| Phase | Tools |
|---|---|
| 1 | Python, Pandas, NumPy, Pandera, Pydantic, PyYAML, Pytest, openpyxl, Git/GitHub |
| 2 | SciPy, Statsmodels, Plotly |
| 3–4 | Scikit-learn, XGBoost (maybe Prophet), LLM API |
| 5 | LangGraph |
| 6 | MCP Python SDK |
| 7 | React + FastAPI (explorer already set up) |
| 8 | Jinja2, PDF library, SMTP/email service |
| 9 | PostgreSQL, SQLAlchemy, APScheduler, logging/monitoring |

## Skills to build

1. Python fundamentals (modules, virtual environments, packaging)
2. Data handling with Pandas
3. Data-quality thinking (business rules, validation, audit logs)
4. Business/KPI understanding (Revenue, Margin, AOV, growth)
5. Statistics (distributions, trends, seasonality, outliers)
6. Machine learning (forecasting, anomaly detection, evaluation)
7. LLM engineering (prompting, grounding, tool calling)
8. Software engineering (structure, config, testing, Git)
9. Integration (MCP, Streamlit, email, databases, scheduling)

## Phase 1 milestones

1. Select and understand the sales dataset
2. Data dictionary and business rules
3. Ingestion module (CSV, Excel)
4. Data profiling report
5. Configurable cleaning policies
6. Modular cleaning functions
7. Validation of the cleaned dataset
8. End-to-end pipeline
9. Tests

Expected Phase 1 output:

```
data/
├── raw/                 # never modified
├── processed/<DATASET_ID>/
│   ├── cleaned_sales.csv
│   ├── quality_report.json
│   ├── cleaning_log.json
│   └── metadata.json
└── quarantine/          # rows that failed rules
```
