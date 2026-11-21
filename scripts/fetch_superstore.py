"""Download the public Superstore sample data into data/raw/superstore/ and verify its fingerprint.

The file is Tableau's "Sample - Superstore" dataset. Its sharing terms are unclear, so it is NOT
committed to git; this script lets anyone fetch exactly the same file.

    python -m harness run -- .venv/Scripts/python -m scripts.fetch_superstore
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://huggingface.co/datasets/Vidulaae/sales-analysis/resolve/main/Sample%20-%20Superstore.csv"
SHA256 = "58fb59c63089e564d835e4aabe19d371757de1137a5bf1888243ae386c4b7a97"
TARGET = ROOT / "data" / "raw" / "superstore" / "Sample - Superstore.csv"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(target: Path = TARGET, url: str = URL, expected: str = SHA256) -> Path:
    if target.exists() and sha256_of(target) == expected:
        print(f"Already present and verified: {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    print(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
        out.write(resp.read())
    actual = sha256_of(tmp)
    if actual != expected:
        tmp.unlink()
        raise ValueError(f"Checksum mismatch: expected {expected}, got {actual}. File rejected.")
    tmp.replace(target)
    print(f"Saved and verified: {target}")
    return target


if __name__ == "__main__":
    try:
        fetch()
    except Exception as e:  # noqa: BLE001 - report any failure clearly
        print(f"ERROR: {e}")
        sys.exit(1)
