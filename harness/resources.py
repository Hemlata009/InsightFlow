"""Resource snapshot and the go / warn / block decision."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import psutil
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

OK, WARN, BLOCK = "OK", "WARN", "BLOCK"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class Snapshot:
    total_mb: int
    available_mb: int
    cpu_percent: float
    disk_free_mb: int

    @classmethod
    def take(cls, cpu_interval: float = 0.5) -> "Snapshot":
        """If Windows can't report (e.g. WinError 1455 under memory pressure), assume the worst: 0 free."""
        try:
            mem = psutil.virtual_memory()
            total, available = mem.total // 2**20, mem.available // 2**20
        except (psutil.Error, OSError):
            total, available = 0, 0
        try:
            disk_free = psutil.disk_usage(str(ROOT)).free // 2**20
        except (psutil.Error, OSError):
            disk_free = 0
        try:
            cpu = psutil.cpu_percent(interval=cpu_interval)
        except (psutil.Error, OSError):
            cpu = 100.0
        return cls(total_mb=total, available_mb=available, cpu_percent=cpu, disk_free_mb=disk_free)


@dataclass
class Verdict:
    level: str
    reasons: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.level != BLOCK


def evaluate(snap: Snapshot, cfg: dict) -> Verdict:
    """Compare a snapshot with the configured limits. Pure function, so it is easy to test."""
    blocks, warns = [], []
    m, c, d = cfg["memory"], cfg["cpu"], cfg["disk"]

    if snap.available_mb < m["block_available_mb"]:
        blocks.append(f"free RAM {snap.available_mb} MB < {m['block_available_mb']} MB")
    elif snap.available_mb < m["warn_available_mb"]:
        warns.append(f"free RAM {snap.available_mb} MB < {m['warn_available_mb']} MB")

    if snap.disk_free_mb < d["block_free_mb"]:
        blocks.append(f"free disk {snap.disk_free_mb} MB < {d['block_free_mb']} MB")
    elif snap.disk_free_mb < d["warn_free_mb"]:
        warns.append(f"free disk {snap.disk_free_mb} MB < {d['warn_free_mb']} MB")

    if snap.cpu_percent >= c["warn_load_percent"]:
        warns.append(f"CPU busy {snap.cpu_percent:.0f}% >= {c['warn_load_percent']}%")

    if blocks:
        return Verdict(BLOCK, blocks + warns)
    if warns:
        return Verdict(WARN, warns)
    return Verdict(OK, [])


def top_processes(n: int = 5) -> list[tuple[str, int]]:
    """Largest processes by memory, to show what to close when RAM is low."""
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        mi = p.info.get("memory_info")
        if mi:
            procs.append((p.info.get("name") or "?", mi.rss // 2**20))
    return sorted(procs, key=lambda x: x[1], reverse=True)[:n]
