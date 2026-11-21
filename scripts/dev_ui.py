"""Live-reload mode for the React explorer: Python API on :8000 + Vite dev server on :5173.

    python -m harness ui --dev       (the harness watches the memory of both)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    npm = shutil.which("npm") or "npm"
    procs = [
        subprocess.Popen([sys.executable, "-m", "insightflow.api", "--port", "8000"], cwd=ROOT),
        subprocess.Popen([npm, "run", "dev"], cwd=ROOT / "web"),
    ]
    print("Explorer (live reload): http://127.0.0.1:5173   API: http://127.0.0.1:8000   Ctrl+C to stop")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
    return max((p.returncode or 0) for p in procs)


if __name__ == "__main__":
    sys.exit(main())
