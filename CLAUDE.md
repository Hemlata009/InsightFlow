# InsightFlow: project instructions

## Local harness (mandatory for every development task)
All tests, scripts and pipeline runs go through the local harness in `harness/`. Never run heavy
commands directly. This machine has only ~6 GB RAM and is often under 1 GB free.

```powershell
.\.venv\Scripts\python -m harness check            # 1. always first: free RAM/CPU/disk
.\.venv\Scripts\python -m harness test -q          # run tests under the guard
.\.venv\Scripts\python -m harness run -- <cmd>     # run any script under the guard
.\.venv\Scripts\python -m harness status           # git + current step + last run + resources
.\.venv\Scripts\python -m harness history          # recent runs (SQLite: .local/harness.db)
```

Rules:
- `[STOP]` from `check`: don't start the task. Tell the user which programs use the most memory.
  Use `--force` only if the user agrees.
- One heavy task at a time. No parallel test runs (`pytest -n`), no parallel agents doing heavy work.
- Data work: read large files in chunks; use small sample data in tests.
- Limits live in `harness/config.yaml`. Change them there, never in code.
- Docker / PostgreSQL are **deferred** (see `docs/harness.md`). Use SQLite for local storage until Phase 9.

## Workflow
- One small step at a time: explain, write the test first, build, run through the harness, document, commit locally (never push).
- Document every discussion in `docs/discussions/`, every decision in `docs/decisions.md`, and update `docs/progress.md`.
- Domain-agnostic core in `src/insightflow/`; domain rules in `configs/*.yaml`.
- Raw data in `data/raw/` is never modified.
