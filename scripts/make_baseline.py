"""Record the verified Phase 1 baseline: results + output fingerprints for each sample file.

    python -m harness run -- python -m scripts.make_baseline
Writes tests/baseline/phase1_baseline.json. tests/test_baseline.py re-runs the pipeline and must match it.
Only re-record on purpose (a deliberate behaviour change), and say why in the commit message.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "baseline" / "phase1_baseline.json"
CASES = [("SALES_002", "sales_messy.csv"), ("SALES_002", "sales_messy.xlsx"), ("SALES_001", "sales_messy.csv")]
RESULT_KEYS = ["status", "rows_input", "rows_output", "rows_quarantined", "rows_duplicates_removed",
               "rows_flagged", "transformations_applied", "validation_errors", "processing_mode"]
FILES = ["cleaned", "quarantine", "duplicates"]


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run_case(ds: str, name: str) -> dict | None:
    from insightflow.pipeline import run_phase1
    src = ROOT / "data" / "sample" / ds / name
    if not src.exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        res = run_phase1(src, ds, data_root=Path(tmp))
        return {"input_sha256": sha(src), "result": {k: res[k] for k in RESULT_KEYS},
                "outputs_sha256": {k: sha(res["output_paths"][k]) for k in FILES}}


def main() -> None:
    baseline = {"description": "Phase 1 verified baseline (frozen 2026-11-21, tag phase1-v1.0)", "cases": {}}
    for ds, name in CASES:
        r = run_case(ds, name)
        if r is None:
            print(f"skip {ds}/{name}: not built")
            continue
        baseline["cases"][f"{ds}/{name}"] = r
        print(f"{ds}/{name}: {r['result']['rows_input']} in, {r['result']['rows_output']} out")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
