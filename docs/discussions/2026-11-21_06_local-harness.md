# 2026-11-21 · Discussion 06: Local harness, resources and local DB

## Request
"Set up the local harness with all the tools needed to monitor development, a local DB Docker container
and everything we may require. Handle memory management. Run tools locally only after checking that
enough resources are available, to avoid hangs or crashes. Fix the harness directory and record it in
the project for every development task." Also: "combine practice and Superstore data."

## Findings
- RAM 5.9 GB total, only ~0.7 GB free (88% used). Biggest users: Windows memory compression, Chrome,
  Edge WebView, Claude, Defender.
- Docker and WSL are not installed. Disk has 12.3 GB free.

## Decisions
1. Harness lives at `harness/` (fixed). It's the only way to run tests and scripts. Recorded in the
   project `CLAUDE.md` and in [../harness.md](../harness.md).
2. Resource guard: refuse to start below 400 MB free RAM, kill a task above 1.5 GB or when system free
   RAM drops below 250 MB, default timeout 15 min. Limits are in `harness/config.yaml`.
3. Run history goes to local SQLite (`.local/harness.db`).
4. **Docker + PostgreSQL deferred to Phase 9.** Installing Docker now would likely freeze this PC and no
   phase before 9 needs a database server. Waiting for the user's final call.
5. Combining practice data and Superstore data: design proposed, waiting for the user's confirmation
   (see [07](2026-11-21_07_dataset-design.md) once written).

## Simple explanation
The harness is like a circuit breaker plus a logbook. Before a job starts, it checks there's enough
power (memory). While the job runs, it trips the breaker if the job draws too much. Every job is written
in the logbook. Docker is like a big generator: useful later, but this PC can't power it right now.

## Technical explanation
- `harness/resources.py`: psutil snapshot plus a pure `evaluate()` → OK / WARN / BLOCK.
- `harness/runner.py`: `subprocess.Popen` + psutil watchdog over the whole process tree (RSS sum),
  kills the tree on a memory limit, critical system RAM, or timeout.
- `harness/db.py`: sqlite3 `runs` table.
- `harness/__main__.py`: argparse CLI; unknown options pass through to pytest.
- pytest `pythonpath = ["."]` so tests can import `harness`. psutil added to the `dev` extra.
- 24 tests pass (14 setup + 10 harness), including a real memory-hog child killed at an 80 MB limit.

## Next steps
Confirm the Docker decision and the combined dataset design, then build Milestone 1.
