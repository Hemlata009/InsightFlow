"""Tests for the local API behind the React explorer."""

import io
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from insightflow.api import create_app

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("apidata")
    shutil.copytree(SAMPLE / "SALES_002", root / "sample" / "SALES_002")
    return TestClient(create_app(data_root=root))


def test_health_and_datasets(client):
    assert client.get("/api/health").json()["status"] == "ok"
    ds = {d["dataset_id"]: d for d in client.get("/api/datasets").json()}
    assert ds["SALES_002"]["locale"] == "en_IN" and "sales_messy.xlsx" in ds["SALES_002"]["samples"]
    assert "answer_key.json" not in ds["SALES_002"]["samples"]          # the answer sheet is not data
    assert ds["SALES_001"]["samples"] == []          # not copied into this test's data folder


def test_rules(client):
    r = client.get("/api/datasets/SALES_002/rules").json()
    assert r["columns"]["Discount"]["max"] == 0.8 and r["locale"]["date_order"] == "DMY"
    assert client.get("/api/datasets/NOPE/rules").status_code == 404
    assert client.get("/api/datasets/..%2Fx/rules").status_code == 404


def test_profile_sample(client):
    r = client.post("/api/profile", data={"dataset_id": "SALES_002", "sample": "sales_messy.xlsx"}).json()
    assert r["ok"] and r["report"]["rows"] == 1013 and r["report"]["findings"]


def test_run_sample_then_browse_results(client):
    res = client.post("/api/run", data={"dataset_id": "SALES_002", "sample": "sales_messy.csv"}).json()
    assert res["status"] == "completed_with_warnings" and res["rows_quarantined"] == 8     # 8 repaired
    latest = client.get("/api/runs/SALES_002/latest").json()
    assert latest["metadata"]["result"]["rows_output"] == 997          # 989 + 8 repaired from the formula
    t = client.get("/api/runs/SALES_002/table/quarantine?limit=5").json()
    assert t["total"] == 8 and len(t["rows"]) == 5 and "_reasons" in t["columns"]
    s = client.get("/api/runs/SALES_002/table/cleaned?search=Laptop&limit=3").json()
    assert s["total"] > 0 and all("Laptop" in " ".join(r.values()) for r in s["rows"])
    log = client.get("/api/runs/SALES_002/log?stage=clean&rule=derived").json()
    assert log["total"] == 4
    assert client.get("/api/runs/SALES_002/table/secrets").status_code == 404


def test_upload_run(client):
    csv = ("Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit\n"
           "IN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,180,10%,20\n")
    r = client.post("/api/run", data={"dataset_id": "SALES_002"},
                    files={"file": ("my upload.csv", io.BytesIO(csv.encode()), "text/csv")}).json()
    assert r["rows_output"] == 1 and r["rows_quarantined"] == 0
    # this file lacks 3 optional columns the previous run of SALES_002 had: reported as a schema change
    assert r["schema_changes"]["removed"] == ["Segment", "State", "Sub_Category"]


def test_upload_rejections(client):
    bad = client.post("/api/run", data={"dataset_id": "SALES_002"},
                      files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert bad.status_code == 400
    trav = client.post("/api/run", data={"dataset_id": "SALES_002", "sample": "../../configs/default.yaml"})
    assert trav.status_code == 400
    none = client.post("/api/run", data={"dataset_id": "SALES_002"})
    assert none.status_code == 400


def test_lab_number(client):
    r = client.post("/api/lab/number", json={"dataset_id": "SALES_002",
                                             "values": ["₹1,00,000", "2.5 Cr", "(500)", "$5", "abc"]}).json()
    vals = [(x["ok"], x.get("value"), x.get("reason")) for x in r["results"]]
    assert vals == [(True, 100000.0, None), (True, 25000000.0, None), (True, -500.0, None),
                    (False, None, "currency_mismatch"), (False, None, "not_a_number")]


def test_lab_date(client):
    r = client.post("/api/lab/date", json={"dataset_id": "SALES_002",
                                           "values": ["05/03/2025", "13-Feb-25", "45746", "31/02/2025"]}).json()
    assert [x["value"] for x in r["results"]] == ["2025-03-05", "2025-02-13", "2025-03-30", None]
    strict = client.post("/api/lab/date", json={"dataset_id": "SALES_002", "values": ["05/03/2025"],
                                                "ambiguous_dates": "quarantine"}).json()
    assert strict["results"][0]["reason"] == "ambiguous_day_month"


def test_lab_date_can_ignore_the_dataset_range(client):
    vals = ["45746", "45746.75", "99999", "1741132800", "20250305"]
    strict = client.post("/api/lab/date", json={"dataset_id": "SALES_001", "values": vals}).json()
    assert all(not x["ok"] and "outside" in x["reason"] for x in strict["results"])
    loose = client.post("/api/lab/date", json={"dataset_id": "SALES_001", "values": vals,
                                               "ignore_date_range": True}).json()
    assert [x["value"] for x in loose["results"]] == ["2025-03-30", "2025-03-30", "2173-10-13", "2025-03-05", "2025-03-05"]
