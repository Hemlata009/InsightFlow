"""Check that the pipeline really works: compare its cleaned output with the known truth.

    python -m harness run -- python -m scripts.check_against_truth SALES_002
    python -m harness run -- python -m scripts.check_against_truth SALES_001

Checks (each PASS/FAIL):
  1. every cleaned value equals the truth (numbers within 0.001; text ignoring invisible spaces;
     blanks allowed only where a value was planted as missing and no rule could fill it)
  2. the rows set aside are exactly the rows planted as bad
  3. the duplicates removed are exactly the planted (+ natural) duplicates
  4. running the CLEANED output again changes nothing
  5. running the TRUTH file gives no set-aside rows, no changes to values
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TEXT = ["Order_ID", "Customer_ID", "Product", "Category", "Region", "Sub_Category", "Segment", "State"]
NUM = ["Quantity", "Unit_Price", "Sales", "Discount", "Profit"]


def messy_to_truth_ids(key) -> dict[int, int]:
    dup_rows = {i["messy_row"] for i in key["planted_issues"] if i["column"] is None}
    mapping, truth_id = {}, 0
    for m in range(key["rows"]["messy"]):
        if m in dup_rows:
            mapping[m] = mapping[m - 1]
        else:
            truth_id += 1
            mapping[m] = truth_id
    return mapping


def read_out(path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)


def main(ds: str) -> int:
    from insightflow.pipeline import run_phase1

    sample = ROOT / "data" / "sample" / ds
    if not (sample / "answer_key.json").exists():
        print(f"{ds}: sample data not built")
        return 2
    key = json.loads((sample / "answer_key.json").read_text(encoding="utf-8"))
    truth = pd.read_csv(sample / "sales_truth.csv", dtype=str, keep_default_na=False)
    truth = truth.set_index(truth["source_row_id"].astype(int))
    to_truth = messy_to_truth_ids(key)
    results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        res = run_phase1(sample / "sales_messy.csv", ds, data_root=tmp / "a")
        clean = read_out(res["output_paths"]["cleaned"])
        clean["truth_id"] = (clean["source_row"].astype(int) - 2).map(to_truth)
        t = truth.loc[clean["truth_id"]].reset_index(drop=True)
        planted_missing = {(to_truth[i["messy_row"]], i["column"]) for i in key["planted_issues"]
                           if i["expected_action"] == "flag_missing"}

        # 1. values
        print(f"\n== {ds}: cleaned output vs truth ({len(clean):,} rows) ==")
        bad_values, filled = 0, 0
        for col in TEXT + NUM + ["Order_Date"]:
            got, exp = clean[col], t[col]
            if col in NUM:
                g, e = pd.to_numeric(got.replace("", None)), pd.to_numeric(exp)
                same = (g - e).abs().le(1e-3) | (g.isna() & e.isna())
            else:
                same = got == exp.str.split().str.join(" ")
                same |= got.str.casefold() == exp.str.split().str.join(" ").str.casefold()   # unknowable capitals
            blanks_ok = pd.Series([(tid, col) in planted_missing for tid in clean["truth_id"]]) & got.eq("")
            wrong = ~(same | blanks_ok)
            bad_values += int(wrong.sum())
            filled += int(sum(1 for tid, v in zip(clean["truth_id"], got) if (tid, col) in planted_missing and v != ""))
            print(f"  {col:<13} {int(same.sum()):>6} equal  {int(blanks_ok.sum()):>3} planted blanks kept  "
                  f"{int(wrong.sum()):>3} WRONG" + (f"  e.g. {got[wrong].iloc[0]!r} vs {exp[wrong].iloc[0]!r}" if wrong.any() else ""))
        results.append(("1. every cleaned value equals the truth", bad_values == 0, f"{bad_values} wrong value(s); "
                        f"{filled} planted blank(s) correctly filled by business rules"))

        # 2. set aside
        planted_bad = {i["messy_row"] + 2 for i in key["planted_issues"] if i["expected_action"] == "quarantine"}
        q = set(read_out(res["output_paths"]["quarantine"])["source_row"].astype(int))
        results.append(("2. set-aside rows = planted bad rows", q == planted_bad,
                        f"{len(q)} set aside, {len(planted_bad)} planted; missed {sorted(planted_bad - q)[:5]}, "
                        f"extra {sorted(q - planted_bad)[:5]}"))

        # 2b. planted problems that are PROVABLY repairable must be kept, repaired and flagged
        planted_fix = {i["messy_row"] + 2 for i in key["planted_issues"] if i["expected_action"] == "repair_from_formula"}
        log_a = json.loads(Path(res["output_paths"]["cleaning_log"]).read_text(encoding="utf-8"))
        repaired = {e["source_row"] for e in log_a if e["rule"] == "repaired_from_formula" and e["kind"] == "flag"}
        kept_rows = set(clean["source_row"].astype(int))
        results.append(("2b. repairable rows = repaired from the formula, kept and flagged",
                        planted_fix <= repaired and planted_fix <= kept_rows,
                        f"{len(planted_fix & repaired)} of {len(planted_fix)} repaired; not repaired "
                        f"{sorted(planted_fix - repaired)[:5]}"))

        # 3. duplicates
        planted_dups = sum(1 for i in key["planted_issues"] if i["expected_action"].endswith("deduplicate"))
        natural = sum(n.get("count", 0) for n in key["natural_issues"] if n["issue_type"] == "exact_duplicate")
        results.append(("3. duplicates removed = planted + natural", res["rows_duplicates_removed"] == planted_dups + natural,
                        f"{res['rows_duplicates_removed']} removed, expected {planted_dups} + {natural}"))

        # 4. cleaned output again
        again = run_phase1(res["output_paths"]["cleaned"], ds, data_root=tmp / "b")
        changed_values = {k: v for k, v in again["transformations_applied"].items()}
        ok4 = again["rows_quarantined"] == 0 and again["rows_duplicates_removed"] == 0 and not changed_values
        results.append(("4. cleaned output run again changes nothing", ok4,
                        f"status {again['status']}, set aside {again['rows_quarantined']}, duplicates "
                        f"{again['rows_duplicates_removed']}, changes {changed_values or 'none'}, flagged {again['rows_flagged']}"))

        # 5. truth file
        tr = run_phase1(sample / "sales_truth.csv", ds, data_root=tmp / "c")
        log5 = json.loads(Path(tr["output_paths"]["cleaning_log"]).read_text(encoding="utf-8"))
        changes5 = [e for e in log5 if e["kind"] == "change" and e["rule"] != "duplicate_removed"]
        # Real data (SALES_001) keeps invisible non-breaking spaces in the truth; tidying them is correct.
        spacing_only = [e for e in changes5 if e["rule"] == "text_standardized"
                        and " ".join(str(e["old"]).split()) == e["new"]]
        other = [e for e in changes5 if e not in spacing_only]
        ok5 = tr["rows_quarantined"] == 0 and not other
        flags5 = {}
        for e in log5:
            if e["kind"] == "flag":
                flags5[e["rule"]] = flags5.get(e["rule"], 0) + 1
        results.append(("5. the truth file passes (only proven spacing fixes allowed)", ok5,
                        f"status {tr['status']}, set aside {tr['rows_quarantined']}, spacing-only fixes "
                        f"{len(spacing_only)}, other changes {len(other)}, duplicates {tr['rows_duplicates_removed']} "
                        f"(natural), flags {flags5 or 'none'}"))

    print(f"\n== {ds}: verdict ==")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        {detail}")
    passed = all(ok for _, ok, _ in results)
    print(f"\n{'ALL CHECKS PASSED' if passed else 'SOME CHECKS FAILED'} for {ds}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "SALES_002"))
