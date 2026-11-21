"""Tests for the local harness: limit logic, watchdog, run history."""

import copy
import sys

from harness import db
from harness.resources import BLOCK, OK, WARN, Snapshot, evaluate, load_config
from harness.runner import run_guarded

CFG = load_config()


def snap(available=3000, cpu=10.0, disk=50_000):
    return Snapshot(total_mb=6000, available_mb=available, cpu_percent=cpu, disk_free_mb=disk)


def test_plenty_of_resources_is_ok():
    assert evaluate(snap(), CFG).level == OK


def test_low_ram_warns():
    v = evaluate(snap(available=800), CFG)
    assert v.level == WARN and v.allowed


def test_very_low_ram_blocks():
    v = evaluate(snap(available=300), CFG)
    assert v.level == BLOCK and not v.allowed


def test_low_disk_blocks():
    assert evaluate(snap(disk=1000), CFG).level == BLOCK


def test_busy_cpu_warns():
    assert evaluate(snap(cpu=95), CFG).level == WARN


def _cfg(tmp_path, **memory):
    cfg = copy.deepcopy(CFG)
    cfg["memory"].update(memory)
    cfg["paths"]["db"] = str(tmp_path / "h.db")
    return cfg


def test_blocked_task_never_starts(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=10**9)  # impossible to satisfy
    marker = tmp_path / "ran.txt"
    res = run_guarded([sys.executable, "-c", f"open(r'{marker}','w')"], cfg=cfg)
    assert res.outcome == "blocked"
    assert not marker.exists()


def test_successful_task_passes(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    res = run_guarded([sys.executable, "-c", "print('hi')"], cfg=cfg)
    assert res.outcome == "passed" and res.exit_code == 0


def test_watchdog_kills_memory_hog(tmp_path):
    # Child grows memory in 10 MB chunks; the limit is 60 MB above its starting size.
    hog = "import time\nx=[]\nfor _ in range(40):\n    x.append(bytearray(10*2**20)); time.sleep(0.1)"
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    res = run_guarded([sys.executable, "-c", hog], cfg=cfg, max_task_mb=80)
    assert res.outcome == "killed_memory"
    assert res.peak_task_mb < 200  # stopped long before reaching 400 MB


def test_timeout_stops_task(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    res = run_guarded([sys.executable, "-c", "import time; time.sleep(30)"], cfg=cfg, timeout=1)
    assert res.outcome == "timeout"
    assert res.duration_s < 10


def test_runs_are_recorded(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    run_guarded([sys.executable, "-c", "pass"], cfg=cfg)
    rows = db.recent(tmp_path / "h.db")
    assert len(rows) == 1 and rows[0][1] == "passed"


def test_relative_venv_python_path_works(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    res = run_guarded([".venv/Scripts/python", "-c", "pass"], cfg=cfg)
    assert res.outcome == "passed"


def test_missing_program_fails_cleanly(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    res = run_guarded(["no-such-program-xyz"], cfg=cfg)
    assert res.outcome == "failed" and "could not start" in res.note


def test_task_can_print_rupee_sign(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    res = run_guarded([sys.executable, "-c", "print('\u20b9 1,00,000')"], cfg=cfg)
    assert res.outcome == "passed"


def test_cwd_option_runs_in_subfolder(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    res = run_guarded([sys.executable, "-c", "import os,sys; sys.exit(0 if os.path.basename(os.getcwd())=='harness' else 3)"],
                      cfg=cfg, cwd="harness")
    assert res.outcome == "passed"
    assert run_guarded([sys.executable, "-c", "pass"], cfg=cfg, cwd="no_such_dir").outcome == "failed"


def test_zero_timeout_means_no_limit(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    res = run_guarded([sys.executable, "-c", "import time; time.sleep(1.2)"], cfg=cfg, timeout=0)
    assert res.outcome == "passed"


def test_low_system_ram_spares_small_tasks(tmp_path):
    # The system is "always low" here, but the task is tiny: it isn't the cause, so it keeps running.
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=10**9,
               critical_grace_seconds=0, critical_min_task_mb=10**6)
    res = run_guarded([sys.executable, "-c", "import time; time.sleep(1)"], cfg=cfg)
    assert res.outcome == "passed"


def test_low_system_ram_stops_big_task_after_grace(tmp_path):
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=10**9,
               critical_grace_seconds=1, critical_min_task_mb=20)
    hog = "import time\nx = bytearray(40 * 2**20)\ntime.sleep(10)"
    res = run_guarded([sys.executable, "-c", hog], cfg=cfg)
    assert res.outcome == "killed_memory"
    assert "while the task used" in res.note
    assert res.duration_s < 8


def test_status_survives_characters_the_console_cannot_print():
    import subprocess
    out = subprocess.run([sys.executable, "-m", "harness", "status"], capture_output=True,
                         env={**__import__("os").environ, "PYTHONIOENCODING": "cp1252"})
    assert out.returncode in (0, 2), out.stderr.decode("cp1252", "replace")[-300:]
    assert b"InsightFlow development status" in out.stdout


def test_watchdog_survives_windows_memory_errors(tmp_path, monkeypatch):
    """WinError 1455 ("paging file too small") from psutil must not crash the guard."""
    import psutil

    import harness.runner as runner
    cfg = _cfg(tmp_path, block_available_mb=0, warn_available_mb=0, critical_available_mb=0)
    real_children = psutil.Process.children

    def flaky_children(self, recursive=False):
        raise OSError(1455, "The paging file is too small for this operation to complete")
    monkeypatch.setattr(psutil.Process, "children", flaky_children)
    res = runner.run_guarded([sys.executable, "-c", "import time; time.sleep(0.6)"], cfg=cfg)
    monkeypatch.setattr(psutil.Process, "children", real_children)
    assert res.outcome == "passed"


def test_unreadable_memory_counts_as_no_free_memory(monkeypatch):
    import psutil

    from harness.resources import Snapshot

    def broken():
        raise OSError(1455, "paging file too small")
    monkeypatch.setattr(psutil, "virtual_memory", broken)
    s = Snapshot.take(0.0)
    assert s.available_mb == 0 and evaluate(s, CFG).level == BLOCK
