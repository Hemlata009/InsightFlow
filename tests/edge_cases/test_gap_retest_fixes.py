"""Issues found by the full Phase 1 re-test (discussion 30), fixed in discussion 31."""

import csv
import shutil

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from insightflow.api import create_app
from insightflow.config import CONFIG_DIR
from insightflow.pipeline import run_phase1
from insightflow.safety import formula_like, protect_formulas, unprotect

H = "Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit"
R = "IN-{i},05/03/2025,C1,{p},Office Supplies,North,2,100,180,0.1,20"


def run(tmp_path, text, large_files="never"):
    cfg = tmp_path / f"cfg_{large_files}"
    if not cfg.exists():
        shutil.copytree(CONFIG_DIR, cfg)
        f = cfg / "datasets" / "SALES_002.yaml"
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        data["policies"].update(large_files=large_files, chunk_rows=10)
        f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    src = tmp_path / "in.csv"
    src.write_text(text, encoding="utf-8")
    return run_phase1(src, "SALES_002", data_root=tmp_path / f"d_{large_files}", config_dir=cfg)


def rows(*products):
    return H + "\n" + "\n".join(R.format(i=i, p=p) for i, p in enumerate(products, 1)) + "\n"


def out(res, kind="cleaned"):
    return pd.read_csv(res["output_paths"][kind], encoding="utf-8-sig", dtype=str, keep_default_na=False)


# ---------------- 1. a giant cell
def test_giant_cell_is_read(tmp_path):
    res = run(tmp_path, rows("P" * 200_000, "Pen Set"))
    assert res["status"] != "failed" and res["rows_output"] == 2


def test_cell_beyond_the_limit_is_a_clear_error(tmp_path):
    old = csv.field_size_limit(1000)
    try:
        res = run(tmp_path, rows("P" * 5000, "Pen Set"))
    finally:
        csv.field_size_limit(old)
    assert res["status"] == "failed" and res["error"]["code"] == "cell_too_large"


# ---------------- 2. a quote that is never closed
@pytest.mark.parametrize("mode", ["never", "always"])
def test_unclosed_quote_sets_aside_one_row_and_reads_the_rest(tmp_path, mode):
    text = rows("Pen Set", '"Stapler', "Notebook", "Laptop")
    res = run(tmp_path, text, mode)
    assert res["rows_input"] == 4 and res["rows_output"] == 3 and res["rows_quarantined"] == 1
    q = out(res, "quarantine")
    assert q.loc[0, "_reasons"] == "unreadable_row:quote never closed" and q.loc[0, "source_row"] == "3"
    assert any("row 3: a quote" in w for w in res["warnings"])
    assert out(res)["Product"].tolist() == ["Pen Set", "Notebook", "Laptop"]


@pytest.mark.parametrize("mode", ["never", "always"])
def test_two_unclosed_quotes(tmp_path, mode):
    res = run(tmp_path, rows('"A', "Pen Set", '"B', "Laptop"), mode)
    assert res["rows_output"] == 2 and res["rows_quarantined"] == 2


def test_proper_quotes_still_work(tmp_path):
    text = H + '\nIN-1,05/03/2025,C1,"Desk, large",Office Supplies,North,2,100,180,0.1,20\n' \
               'IN-2,05/03/2025,C1,"Two\nlines",Office Supplies,North,2,100,180,0.1,20\n' \
               'IN-3,05/03/2025,C1,24" Monitor,Office Supplies,North,2,100,180,0.1,20\n' \
               'IN-4,05/03/2025,C1,"say ""hi""",Office Supplies,North,2,100,180,0.1,20\n'
    res = run(tmp_path, text)
    assert res["rows_output"] == 4 and res["rows_quarantined"] == 0
    assert out(res)["Product"].tolist() == ["Desk, large", "Two lines", '24" Monitor', 'say "hi"']  # break -> space


def test_unclosed_quote_in_the_header_is_refused(tmp_path):
    res = run(tmp_path, '"Order_ID,' + rows("Pen Set").split(",", 1)[1])
    assert res["status"] == "failed" and res["error"]["code"] == "corrupt_file"
    assert "never closed" in res["error"]["message"]


# ---------------- 3. text a spreadsheet would run as a formula
@pytest.mark.parametrize("mode", ["never", "always"])
def test_formula_text_is_marked_and_written_safely(tmp_path, mode):
    res = run(tmp_path, rows('=HYPERLINK("http://evil.example")', "@SUM(A1)", "Pen Set"), mode)
    assert res["rows_output"] == 3 and res["rows_flagged"] == 2
    products = out(res)["Product"].tolist()
    assert products[:2] == ["'=HYPERLINK(\"http://evil.example\")", "'@SUM(A1)"] and products[2] == "Pen Set"
    assert [unprotect(p) for p in products[:2]] == ['=HYPERLINK("http://evil.example")', "@SUM(A1)"]
    log = pd.read_json(res["output_paths"]["cleaning_log"])
    assert (log["rule"] == "formula_like_text").sum() == 2


def test_formula_text_in_the_set_aside_file_is_safe_too(tmp_path):
    text = H + '\nIN-1,31/02/2025,C1,=cmd|x,Office Supplies,North,2,100,180,0.1,20\n'   # impossible date
    res = run(tmp_path, text)
    assert out(res, "quarantine").loc[0, "Product"] == "'=cmd|x"


def test_what_counts_as_formula_like():
    s = pd.Series(["=1+1", "@x", "+cmd", "-2+3(", "+91 98765 43210", "-20", "Pen", None, "a=b"], dtype="string")
    assert formula_like(s).tolist() == [True, True, True, True, False, False, False, False, False]
    assert formula_like(pd.Series([1.5, -2.0])).tolist() == [False, False]
    assert protect_formulas(pd.DataFrame({"x": s}))["x"].iloc[0] == "'=1+1"
    assert unprotect("'Pen") == "'Pen" and unprotect("'=1") == "=1"


# ---------------- 4. the lab completes partial dates like a run
def test_lab_completes_partial_dates_like_a_run(tmp_path):
    client = TestClient(create_app(data_root=tmp_path))
    body = {"dataset_id": "SALES_002", "values": ["Mar 2025", "05/03", "05/03/2025", "31/02/2025"]}
    r = {x["input"]: x for x in client.post("/api/lab/date", json=body).json()["results"]}
    assert r["Mar 2025"]["ok"] and r["Mar 2025"]["value"] == "2025-03-01"
    assert r["Mar 2025"]["how"] == "partial_date:missing_day:first_of_month (completed and marked)"
    assert r["05/03"]["ok"] and r["05/03"]["value"] == "2025-03-05"       # year = most common typed year
    assert not r["31/02/2025"]["ok"]


def test_lab_partial_date_with_nothing_to_learn_from(tmp_path):
    client = TestClient(create_app(data_root=tmp_path))
    r = client.post("/api/lab/date", json={"dataset_id": "SALES_002", "values": ["05/03"]}).json()["results"][0]
    assert not r["ok"] and "found nothing" in r["reason"]
