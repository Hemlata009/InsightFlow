# Local Development Harness

The harness is the single entry point for every local development task: tests, scripts, and later the
pipeline, the MCP server and Streamlit. It protects this low-memory PC from hangs and records every run.

## Machine profile (measured 2026-11-21)
| Resource | Value |
|---|---|
| RAM | 5.9 GB total, usually **0.7–0.9 GB free** (88% used) |
| CPU | AMD Ryzen 5 5600H, 6 cores / 12 threads |
| Disk C: | 12.3 GB free of 230 GB |
| Docker / WSL | Not installed |

## Commands
| Command | What it does |
|---|---|
| `python -m harness check` | Free RAM/CPU/disk → `[OK]`, `[WARN]` or `[STOP]`, plus the biggest memory users |
| `python -m harness test [pytest args]` | Runs pytest under the guard |
| `python -m harness run -- <cmd>` | Runs any command under the guard |
| `python -m harness status` | Branch, last commit, uncommitted files, current step, last run, resources |
| `python -m harness history [-n 20]` | Recent runs from the SQLite history |

Options for `test` and `run`: `--force` (start despite low resources), `--timeout <s>`.

## How the guard works
1. **Before start:** checks free RAM, disk and CPU against `harness/config.yaml`.
   Below `block_available_mb` (400 MB) or `block_free_mb` (2 GB disk) the task is **not started**.
2. **While running:** a watchdog checks every 0.25 s and kills the task and all its child processes if:
   - the task uses more than `max_task_mb` (1500 MB), or
   - system free RAM falls below `critical_available_mb` (250 MB), or
   - it runs past the timeout (default 900 s).
3. **After:** the outcome (`passed`, `failed`, `blocked`, `killed_memory`, `timeout`), duration, peak
   memory and lowest free RAM are saved to `.local/harness.db` (SQLite, ignored by git).

## Local database decision
- **Now (Phases 1–8):** SQLite, built into Python, no server, near-zero RAM. Used for harness history.
- **Docker + PostgreSQL: deferred to Phase 9**, when the product actually needs a database server.
  - Docker Desktop on Windows needs WSL2 (not installed), admin rights, a reboot, ~2–4 GB RAM and
    several GB of disk. With ~0.8 GB free RAM it would likely freeze this PC.
  - When Phase 9 arrives: either free/upgrade RAM and install Docker Desktop, or install PostgreSQL
    natively (~100–200 MB RAM), or use a free cloud PostgreSQL.

## Tests
`tests/harness/test_harness.py`: limit logic, refuse-to-start, memory-hog kill, timeout, history recording.

## Growing the harness (add only when a phase needs it)
- Phase 6: `harness run -- python -m insightflow.mcp` (MCP server)
- Phase 7: `harness run -- streamlit run ...`
- Phase 9: `harness db` commands for PostgreSQL, if Docker or native Postgres is installed
