# 2026-11-21 · Discussion 12: React explorer (UI) for Phase 1

## Request
"I already shared some edge cases earlier, so before going ahead I want you to set up React, so that I
can explore more and directly."

Note: the user's earlier edge-case list is already the Phase 1 test backlog
([../phase1-plan.md](../phase1-plan.md)). Its "Deferred" section lists what isn't covered yet.

## Decisions
1. **React (Vite + TypeScript) replaces Streamlit** as the UI technology (the user asked for React).
   The React app talks to a small **FastAPI** service that wraps the same Phase 1 engine code.
2. **Local only:** the API binds to `127.0.0.1` (never the network), runs one pipeline at a time, and
   only accepts `.csv` / `.xlsx` uploads under the rule book's `max_file_mb`. Uploads go to
   `data/uploads/` (git-ignored). Sample names can't escape `data/sample/<ID>/`.
3. **Low-RAM friendly:** normal use = one process (FastAPI serves the built React files). Live-reload
   dev mode (Vite + API) is optional.
4. **`python -m harness ui`** is the only way to start it: it installs and builds when needed, then
   runs under the memory watchdog. Ctrl+C stops everything.
5. **Rule:** don't run the test suite while the explorer is running. Doing it once dropped free RAM
   to 230 MB and the harness stopped both. The protection worked, but it was avoidable.

## What the explorer shows
| Tab | What you can do |
|---|---|
| Run pipeline | Pick a sample or upload a file → "Run full pipeline" or "Health check only". See status, counts, what changed, failed checks, warnings. Browse **Set aside** (original text + reasons), **Clean data**, **Duplicates removed**, **Change log** (filter by stage/rule), **Health check** findings. Click a row number to trace every change made to that row. |
| Edge-case lab | Type any values (one per line) and see how the engine reads them as **numbers/money** or **dates**, using the selected dataset's locale. Preset groups: Indian style, international, negatives & %, Excel dates, "should be refused". Switch the dataset to compare India vs US. |
| Rule book | Read-only view of the merged config: locale, date range, columns (type, required, missing policy, derive formula, range, allowed values, header aliases), business rules, duplicate policy, general policies. |

## Simple explanation
The engine was a machine with only a command-line switch. Now it has a control panel: buttons to run
it, windows to look inside (clean rows, rejected rows and why, every change), and a test bench where
you feed in single values and watch what comes out.

## Technical explanation
- `src/insightflow/api/app.py`: `create_app(data_root, config_dir)`. Endpoints: `GET /api/health`,
  `GET /api/datasets`, `GET /api/datasets/{id}/rules`, `POST /api/profile`, `POST /api/run`
  (multipart: dataset_id + sample | file), `GET /api/runs/{id}/latest`,
  `GET /api/runs/{id}/table/{cleaned|quarantine|duplicates}?offset&limit&search`,
  `GET /api/runs/{id}/log?stage&rule&row`, `POST /api/lab/number`, `POST /api/lab/date`.
  The built SPA is served from `web/dist`, with a fallback to `index.html`.
- `web/`: React 19 + Vite 8 + TypeScript (strict). `src/api.ts` (typed client), `App.tsx` (dataset
  picker + tabs), `pages/RunPage|LabPage|RulesPage.tsx`, `components/DataTable|ChangeLog.tsx`,
  plain CSS with light/dark. Build: 240 KB JS (74 KB gzipped). No UI framework.
- Harness: `ui` command, `run --cwd <folder>`, `--timeout 0` = no limit, Ctrl+C → outcome `stopped`.
  `scripts/dev_ui.py` runs API + Vite together for `--dev`.
- Tests: `tests/test_api.py` (8): health, datasets, rules, profile, run + browse tables/log/search,
  upload, rejections (bad extension, path traversal, no input), lab number/date. Plus 2 harness tests.
  Total: 266 passing. API server ≈ 125 MB while running.

## Next steps
The user explores the UI, then we discuss edge cases and new requirements.
