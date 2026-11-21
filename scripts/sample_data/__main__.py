"""Build the sample datasets.

    python -m harness run -- .venv/Scripts/python -m scripts.sample_data
"""

from __future__ import annotations

from pathlib import Path

from scripts.fetch_superstore import TARGET

from . import india, superstore

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"


def main() -> None:
    from . import chaos
    ck = chaos.build(SAMPLE / "SALES_003")
    print(f"SALES_003 (chaos): {len(ck['cases'])} cases")
    key = india.build(SAMPLE / india.DATASET_ID)
    print(f"{india.DATASET_ID}: {key['rows']} | issues {sum(key['planted_issue_counts'].values())}")
    if TARGET.exists():
        key = superstore.build(SAMPLE / superstore.DATASET_ID)
        print(f"{superstore.DATASET_ID}: {key['rows']} | issues {sum(key['planted_issue_counts'].values())}")
    else:
        print(f"{superstore.DATASET_ID}: skipped. Run scripts.fetch_superstore first.")


if __name__ == "__main__":
    main()
