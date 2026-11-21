"""Local SQLite store for harness run history (no server needed, built into Python)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    command         TEXT NOT NULL,
    verdict         TEXT NOT NULL,
    outcome         TEXT NOT NULL,      -- passed | failed | blocked | killed_memory | timeout
    exit_code       INTEGER,
    duration_s      REAL,
    peak_task_mb    INTEGER,
    min_free_mb     INTEGER,
    note            TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def record(path: Path, **row) -> None:
    row.setdefault("started_at", datetime.now().isoformat(timespec="seconds"))
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with closing(connect(path)) as conn, conn:
        conn.execute(f"INSERT INTO runs ({cols}) VALUES ({marks})", tuple(row.values()))


def recent(path: Path, limit: int = 10) -> list[tuple]:
    if not path.exists():
        return []
    with closing(connect(path)) as conn:
        return conn.execute(
            "SELECT started_at, outcome, duration_s, peak_task_mb, min_free_mb, command "
            "FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
