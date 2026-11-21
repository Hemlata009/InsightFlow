"""SALES_003 chaos file: every row is one problem; each must end up exactly as the answer key says."""

from pathlib import Path

import pytest

from scripts.check_chaos import SAMPLE, report, run_file


@pytest.mark.parametrize("name", ["chaos.csv", "chaos.xlsx"])
def test_every_chaos_row_as_expected(name, tmp_path, capsys):
    res, graded = run_file(name, tmp_path)
    ok = report(name, res, graded)
    out = capsys.readouterr().out
    failed = [f"{g['case']} row {g['row']}: {g['detail']}" for g in graded if not g["ok"]]
    assert ok and not failed, "\n".join(failed) or out[-2000:]


def test_chaos_chunked_mode_gives_the_same_outcomes(tmp_path, capsys):
    from scripts.check_chaos import main
    assert main(["--chunked"]) == 0, capsys.readouterr().out[-2500:]


def test_chaos_files_are_reproducible(tmp_path):
    from scripts.sample_data.chaos import build
    build(tmp_path)
    for name in ["chaos.csv", "answer_key.json"]:
        assert (tmp_path / name).read_bytes() == (SAMPLE / name).read_bytes(), name
    assert Path(SAMPLE / "chaos.xlsx").exists()
