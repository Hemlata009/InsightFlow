"""Run the Phase 1 pipeline from the command line.

    python -m harness run -- python -m insightflow.pipeline data/sample/SALES_002/sales_messy.xlsx SALES_002
"""

from __future__ import annotations

import argparse
import json
import sys

from .phase1 import describe, run_phase1


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m insightflow.pipeline")
    p.add_argument("file")
    p.add_argument("dataset_id")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = p.parse_args()
    result = run_phase1(a.file, a.dataset_id)
    print(json.dumps(result, indent=2, default=str) if a.json else describe(result))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
