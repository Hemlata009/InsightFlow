"""Priority 5: the frozen Phase 1 baseline must be reproduced exactly (results + output file fingerprints).

If this fails after a change, either the change is a bug, or it is a deliberate behaviour change:
then re-record with `python -m harness run -- python -m scripts.make_baseline` and explain why in the commit.
"""

import json

import pytest

from scripts.make_baseline import CASES, OUT, run_case

BASELINE = json.loads(OUT.read_text(encoding="utf-8"))


@pytest.mark.parametrize("ds, name", CASES)
def test_phase1_baseline_reproduced(ds, name):
    key = f"{ds}/{name}"
    now = run_case(ds, name)
    if now is None:
        pytest.skip(f"{key} not built on this machine")
    if key not in BASELINE["cases"]:
        pytest.skip(f"{key} not in the recorded baseline")
    expected = BASELINE["cases"][key]
    assert now["input_sha256"] == expected["input_sha256"], "the sample input itself changed"
    assert now["result"] == expected["result"]
    assert now["outputs_sha256"] == expected["outputs_sha256"]
