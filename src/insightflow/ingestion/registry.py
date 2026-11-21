"""Remember which files were already ingested (by SHA-256), so a repeated upload is noticed."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .reader import FileMetadata


class FileRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def lookup(self, sha256: str) -> dict | None:
        return self._load().get(sha256)

    def register(self, meta: FileMetadata, dataset_id: str | None = None) -> tuple[bool, dict]:
        """Returns (is_new, entry). A repeat keeps the FIRST entry and counts the repeat."""
        data = self._load()
        now = datetime.now().isoformat(timespec="seconds")
        if meta.sha256 in data:
            entry = data[meta.sha256]
            entry["times_seen"] = entry.get("times_seen", 1) + 1
            entry["last_seen"] = now
            is_new = False
        else:
            entry = {"file_name": meta.file_name, "dataset_id": dataset_id, "first_seen": now,
                     "last_seen": now, "times_seen": 1, "size_bytes": meta.size_bytes}
            data[meta.sha256] = entry
            is_new = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return is_new, entry
