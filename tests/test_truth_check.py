"""The cleaned output must match the known truth: the same 5 checks as scripts/check_against_truth.py."""

from pathlib import Path

import pytest

from scripts.check_against_truth import main

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.mark.parametrize("ds", ["SALES_002", "SALES_001"])
def test_all_truth_checks_pass(ds, capsys):
    if not (SAMPLE / ds / "answer_key.json").exists():
        pytest.skip(f"{ds} not built")
    code = main(ds)
    out = capsys.readouterr().out
    assert code == 0, out[-2500:]
    assert out.count("  PASS  ") == 5 and "  FAIL  " not in out
