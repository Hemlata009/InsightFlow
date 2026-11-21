"""Run the chaos files through the pipeline and grade EVERY row against the answer key.

    python -m harness run -- python -m scripts.check_chaos            # both files
    python -m harness run -- python -m scripts.check_chaos --chunked  # also big-file mode on the CSV
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample" / "SALES_003"


def _read(p) -> pd.DataFrame:
    return pd.read_csv(p, encoding="utf-8-sig", dtype=str, keep_default_na=False)


def _same(got: str, exp) -> bool:
    if isinstance(exp, (int, float)):
        try:
            return abs(float(got) - float(exp)) < 1e-6
        except ValueError:
            return False
    return got == str(exp)


def grade(res: dict, expected_rows: list[dict]) -> list[dict]:
    p = res["output_paths"]
    clean = _read(p["cleaned"]).set_index("source_row")
    quar = _read(p["quarantine"]).set_index("source_row")
    dups = _read(p["duplicates"]).set_index("source_row")
    log = json.loads(Path(p["cleaning_log"]).read_text(encoding="utf-8"))
    flags: dict[str, list[str]] = {}
    for e in log:
        if e["kind"] == "flag" and e["source_row"] is not None:
            flags.setdefault(str(e["source_row"]), []).append(e["rule"])
    out = []
    for exp in expected_rows:
        row, want = str(exp["row"]), exp["outcome"]
        where = ("kept" if row in clean.index else "set aside" if row in quar.index else
                 "duplicate" if row in dups.index else "MISSING")
        detail, ok = where, False
        if want in ("keep", "flag"):
            ok = where == "kept"
            if ok and exp.get("values"):
                for col, v in exp["values"].items():
                    got = clean.at[row, col]
                    if not _same(got, v):
                        ok, detail = False, f"kept, but {col}={got!r} (expected {v!r})"
                        break
            if ok and want == "flag":
                ok = any(exp["rule"] in f for f in flags.get(row, []))
                detail = f"kept, flags {flags.get(row, [])}"
        elif want == "quarantine":
            reason = quar.at[row, "_reasons"] if where == "set aside" else ""
            ok = where == "set aside" and exp["reason"] in reason
            detail = f"{where}: {reason}" if reason else where
        elif want == "duplicate":
            ok = where == "duplicate"
            detail = f"duplicate of row {dups.at[row, 'duplicate_of']}" if ok else where
        out.append({**exp, "ok": ok, "detail": detail})
    return out


def run_file(name: str, data_root: Path, config_dir: Path | None = None) -> tuple[dict, list[dict]]:
    from insightflow.pipeline import run_phase1
    key = json.loads((SAMPLE / "answer_key.json").read_text(encoding="utf-8"))
    kwargs = {"config_dir": config_dir} if config_dir else {}
    res = run_phase1(SAMPLE / name, "SALES_003", data_root=data_root, **kwargs)
    return res, grade(res, key["files"][name]["rows"])


def report(name: str, res: dict, graded: list[dict]) -> bool:
    key = json.loads((SAMPLE / "answer_key.json").read_text(encoding="utf-8"))
    desc = {c["id"]: (c["group"], c["description"]) for c in key["cases"]}
    print(f"\n== {name}: status {res['status']} | in {res['rows_input']}, kept {res['rows_output']}, "
          f"set aside {res['rows_quarantined']}, duplicates {res['rows_duplicates_removed']}, flagged {res['rows_flagged']} ==")
    group = None
    for g in graded:
        grp, d = desc.get(g["case"], ("?", "?"))
        if grp != group:
            print(f"  -- {grp} --")
            group = grp
        print(f"  {'PASS' if g['ok'] else 'FAIL'}  {g['case']:<4} row {g['row']:<4} {d:<48} -> {g['detail'][:90]}")
    accounted = res["rows_output"] + res["rows_quarantined"] + res["rows_duplicates_removed"] == res["rows_input"]
    print(f"  notes   : {res.get('notes')}")
    print(f"  warnings: {res['warnings']}")
    fails = [g for g in graded if not g["ok"]]
    print(f"  {len(graded) - len(fails)}/{len(graded)} rows as expected; every row accounted for: {accounted}; "
          f"status needs_review (too many bad rows): {res['status'] == 'needs_review'}")
    return not fails and accounted and res["status"] == "needs_review"


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in ["chaos.csv", "chaos.xlsx"]:
            res, graded = run_file(name, tmp / name)
            ok &= report(name, res, graded)
        if "--chunked" in argv:
            from insightflow.config import CONFIG_DIR
            cfg_dir = tmp / "cfg"
            shutil.copytree(CONFIG_DIR, cfg_dir)
            f = cfg_dir / "datasets" / "SALES_003.yaml"
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            data.setdefault("policies", {}).update(large_files="always", chunk_rows=15)
            f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
            res, graded = run_file("chaos.csv", tmp / "chunked", cfg_dir)
            ok &= report("chaos.csv in CHUNKED mode (pieces of 15 rows)", res, graded)
    print(f"\n{'ALL CHAOS CHECKS PASSED' if ok else 'SOME CHAOS CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
