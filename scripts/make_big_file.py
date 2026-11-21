"""Make a large messy CSV (for testing chunked mode) by repeating SALES_002's messy rows with new order IDs.

    python -m harness run -- python -m scripts.make_big_file 600000
Writes data/raw/demo/big_sales.csv (git-ignored). Streams line by line: uses almost no memory.
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(rows: int) -> Path:
    src = ROOT / "data" / "sample" / "SALES_002" / "sales_messy.csv"
    out = ROOT / "data" / "raw" / "demo" / "big_sales.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(src, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        header, base = next(reader), list(reader)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        n = 0
        while n < rows:
            copy = n // len(base)
            for r in base:
                if n >= rows:
                    break
                r = list(r)
                r[0] = f"{r[0].strip()}-{copy}"       # new order id per copy: copies are not duplicates
                w.writerow(r)
                n += 1
    print(f"wrote {rows:,} rows, {out.stat().st_size / 2**20:.1f} MB -> {out}")
    return out


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 600_000)
