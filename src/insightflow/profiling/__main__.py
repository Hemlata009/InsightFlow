"""Profile one file from the command line.

    python -m harness run -- python -m insightflow.profiling data/sample/SALES_002/sales_messy.csv SALES_002
    (add --out report.json to save the full report)
"""

from __future__ import annotations

import argparse
import sys

from insightflow.config import load_dataset_config
from insightflow.ingestion import IngestionError, read_file

from .profiler import profile, summary_text, write_report


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m insightflow.profiling")
    p.add_argument("file")
    p.add_argument("dataset_id")
    p.add_argument("--out", help="save the full JSON report here")
    a = p.parse_args()
    cfg = load_dataset_config(a.dataset_id)
    try:
        r = read_file(a.file, known_headers=set(cfg.header_map()))
    except IngestionError as e:
        print(f"Cannot read file: {e}")
        return 1
    for w in r.warnings:
        print(f"  [READ   ] {w}")
    report = profile(r.data, cfg, r.metadata)
    print(summary_text(report))
    if a.out:
        print(f"Saved: {write_report(report, a.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
