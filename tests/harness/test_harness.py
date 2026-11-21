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
