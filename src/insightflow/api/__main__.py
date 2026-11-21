"""Start the local API (+ the built React app if web/dist exists).

    python -m harness ui            # recommended: guarded, builds the UI if needed
    python -m insightflow.api [--port 8000]
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m insightflow.api")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    print(f"InsightFlow explorer: http://127.0.0.1:{a.port}  (press Ctrl+C to stop)")
    # 127.0.0.1 only: never exposed to the network. One worker: low-RAM PC.
    uvicorn.run("insightflow.api.app:app", host="127.0.0.1", port=a.port, workers=1, log_level="warning")


if __name__ == "__main__":
    main()
