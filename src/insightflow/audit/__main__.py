"""Trace one row of the original file through the last run of a dataset.

    python -m insightflow.audit trace SALES_002 42
"""

from __future__ import annotations

import argparse
import json
import sys

from insightflow.pipeline.phase1 import DATA_ROOT

from .log import trace


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m insightflow.audit")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trace", help="show every change, flag and rejection for one original row")
    t.add_argument("dataset_id")
    t.add_argument("row", type=int)
    a = p.parse_args()
    log_path = DATA_ROOT / "processed" / a.dataset_id / "cleaning_log.json"
    if not log_path.exists():
        print(f"No run yet for {a.dataset_id}")
        return 1
    entries = trace(json.loads(log_path.read_text(encoding="utf-8")), a.row)
    if not entries:
        print(f"Row {a.row}: nothing was changed, flagged or rejected.")
        return 0
    print(f"Row {a.row} of the original file ({len(entries)} event(s), run {entries[0]['run_id']}):")
    for e in entries:
        col = f"{e['column']}: " if e["column"] else ""
        change = f"{e['old']!r} -> {e['new']!r}" if e["kind"] in ("change", "plugin_change") else f"value {e['old']!r}"
        print(f"  #{e['seq']:<6} {e['kind']:<13} {e['stage']:<9} {col}{e['rule']}  {change}"
              + (f"  ({e['detail']})" if e["detail"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
