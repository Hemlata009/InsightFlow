"""Guarded task runner: check resources first, then watch the task and stop it before it can hang the PC."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from . import db
from .resources import BLOCK, ROOT, Snapshot, Verdict, evaluate, load_config


@dataclass
class RunResult:
    outcome: str  # passed | failed | blocked | killed_memory | timeout
    exit_code: int | None
    duration_s: float
    peak_task_mb: int
    min_free_mb: int
    verdict: Verdict
    note: str = ""


def _tree_rss_mb(proc: psutil.Process) -> int:
    """Memory used by the task and all of its child processes."""
    total = 0
    try:
        for p in [proc, *proc.children(recursive=True)]:
            try:
                total += p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except psutil.NoSuchProcess:
        pass
    return total // 2**20


def _kill_tree(proc: psutil.Process) -> None:
    try:
        procs = [*proc.children(recursive=True), proc]
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=5)


def resolve_command(cmd: list[str]) -> list[str]:
    """Make the program path work on Windows: `python` means this venv's Python, and relative
    paths (e.g. `.venv/Scripts/python`) are resolved against the project root."""
    prog = cmd[0]
    if prog in ("python", "python3", "py"):
        return [sys.executable, *cmd[1:]]
    candidate = (ROOT / prog)
    found = shutil.which(str(candidate)) if not Path(prog).is_absolute() else None
    return [found or shutil.which(prog) or prog, *cmd[1:]]


def wait_for_resources(cfg: dict, seconds: float) -> Verdict:
    deadline = time.monotonic() + seconds
    verdict = evaluate(Snapshot.take(), cfg)
    while not verdict.allowed and time.monotonic() < deadline:
        time.sleep(2)
        verdict = evaluate(Snapshot.take(), cfg)
    return verdict


def run_guarded(
    cmd: list[str],
    *,
    cfg: dict | None = None,
    force: bool = False,
    timeout: float | None = None,
    max_task_mb: int | None = None,
    record_history: bool = True,
    cwd: str | Path | None = None,
) -> RunResult:
    cfg = cfg or load_config()
    m, r = cfg["memory"], cfg["runner"]
    timeout = r["default_timeout_seconds"] if timeout is None else timeout
    max_task_mb = max_task_mb or m["max_task_mb"]
    db_path = ROOT / cfg["paths"]["db"]

    verdict = wait_for_resources(cfg, r["wait_for_resources_seconds"])
    if verdict.level == BLOCK and not force:
        res = RunResult("blocked", None, 0.0, 0, Snapshot.take(0.1).available_mb, verdict)
        _save(db_path, cmd, res, record_history)
        return res

    workdir = (ROOT / cwd).resolve() if cwd else ROOT
    if not workdir.is_dir():
        res = RunResult("failed", None, 0.0, 0, Snapshot.take(0.1).available_mb, verdict, f"no such folder: {workdir}")
        _save(db_path, cmd, res, record_history)
        return res
    cmd = resolve_command(cmd)
    start = time.monotonic()
    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}  # print ₹ safely
        popen = subprocess.Popen(cmd, cwd=workdir, env=env)
    except OSError as e:
        res = RunResult("failed", None, 0.0, 0, Snapshot.take(0.1).available_mb, verdict,
                        f"could not start {cmd[0]!r}: {e.strerror or e}")
        _save(db_path, cmd, res, record_history)
        return res
    proc = psutil.Process(popen.pid)

    try:
        outcome, note, peak, min_free = _watch(popen, proc, m, r, start, timeout, max_task_mb)
    except KeyboardInterrupt:                   # Ctrl+C: stop the task and everything it started
        _kill_tree(proc)
        outcome, note, peak, min_free = "stopped", "stopped by user (Ctrl+C)", 0, 10**9

    code = popen.wait()
    if outcome is None:
        outcome = "passed" if code == 0 else "failed"
    min_free = min(min_free, psutil.virtual_memory().available // 2**20)
    res = RunResult(outcome, code, round(time.monotonic() - start, 2), peak, min_free, verdict, note)
    _save(db_path, cmd, res, record_history)
    return res


def _watch(popen, proc, m, r, start, timeout, max_task_mb):
    peak, min_free, outcome, note = 0, 10**9, None, ""
    low_since = None
    while popen.poll() is None:
        used = _tree_rss_mb(proc)
        free = psutil.virtual_memory().available // 2**20
        peak, min_free = max(peak, used), min(min_free, free)
        if used > max_task_mb:
            outcome, note = "killed_memory", f"task used {used} MB > limit {max_task_mb} MB"
        elif free < m["critical_available_mb"]:
            low_since = low_since or time.monotonic()
            lasted = time.monotonic() - low_since
            if lasted >= m.get("critical_grace_seconds", 0) and used >= m.get("critical_min_task_mb", 0):
                outcome, note = "killed_memory", (f"system free RAM {free} MB < {m['critical_available_mb']} MB "
                                                  f"for {lasted:.0f}s while the task used {used} MB")
        else:
            low_since = None
        if outcome is None and timeout > 0 and time.monotonic() - start > timeout:
            outcome, note = "timeout", f"exceeded {timeout:.0f} s"
        if outcome:
            _kill_tree(proc)
            break
        time.sleep(r["poll_seconds"])
    return outcome, note, peak, min_free


def _save(db_path, cmd, res: RunResult, enabled: bool) -> None:
    if not enabled:
        return
    db.record(
        db_path,
        command=" ".join(cmd),
        verdict=res.verdict.level,
        outcome=res.outcome,
        exit_code=res.exit_code,
        duration_s=res.duration_s,
        peak_task_mb=res.peak_task_mb,
        min_free_mb=res.min_free_mb,
        note=res.note or "; ".join(res.verdict.reasons),
    )
