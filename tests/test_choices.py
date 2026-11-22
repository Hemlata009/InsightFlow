"""Missing-value choices saved from the web page: rule book layer 4 (configs/choices/<ID>.yaml)."""

import shutil
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from insightflow.api import create_app
from insightflow.config import CONFIG_DIR, load_dataset_config, save_choices
from insightflow.pipeline import run_phase1

ROOT = Path(__file__).resolve().parents[1]
HEADER = "Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit"


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("INSIGHTFLOW_IGNORE_CHOICES", raising=False)   # this file tests the choices layer itself
    d = tmp_path / "configs"
    shutil.copytree(CONFIG_DIR, d, ignore=shutil.ignore_patterns("choices"))
    return d


@pytest.fixture
def client(tmp_path, cfg_dir):
    return TestClient(create_app(data_root=tmp_path / "data", config_dir=cfg_dir))


def test_saved_choice_is_used_by_the_run(tmp_path, cfg_dir):
    save_choices("SALES_002", {"Region": {"missing_policy": "fill_value", "fill_value": "Central"}}, cfg_dir)
    assert load_dataset_config("SALES_002", cfg_dir).columns["Region"].fill_value == "Central"
    src = tmp_path / "in.csv"
    src.write_text(HEADER + "\nIN-1,05/03/2025,C1,Pen Set,Office Supplies,,2,100,180,0.1,20\n", encoding="utf-8")
    res = run_phase1(src, "SALES_002", data_root=tmp_path / "data", config_dir=cfg_dir)
    out = pd.read_csv(res["output_paths"]["cleaned"], encoding="utf-8-sig", dtype=str)
    assert out["Region"].tolist() == ["Central"]


@pytest.mark.parametrize("col, value, msg", [("Region", "Unknown", "not one of the allowed values"),
                                             ("Discount", 0.95, "outside"), ("Quantity", "abc", "not a number")])
def test_fixed_value_must_itself_be_valid(cfg_dir, col, value, msg):
    with pytest.raises(ValueError, match=msg):
        save_choices("SALES_002", {col: {"missing_policy": "fill_value", "fill_value": value}}, cfg_dir)


def test_invalid_choice_is_not_saved(cfg_dir):
    with pytest.raises(ValueError, match="BR-9"):
        save_choices("SALES_002", {"Profit": {"missing_policy": "fill_down"}}, cfg_dir)
    assert not (cfg_dir / "choices" / "SALES_002.yaml").exists()


def test_only_missing_value_settings_allowed(cfg_dir):
    with pytest.raises(ValueError, match="only missing-value settings"):
        save_choices("SALES_002", {"Discount": {"max": 0.99}}, cfg_dir)
    (cfg_dir / "choices").mkdir()
    (cfg_dir / "choices" / "SALES_002.yaml").write_text("policies: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="only 'columns'"):
        load_dataset_config("SALES_002", cfg_dir)


def test_tests_ignore_saved_choices(cfg_dir, monkeypatch):
    save_choices("SALES_002", {"Region": {"missing_policy": "fill_value", "fill_value": "North"}}, cfg_dir)
    monkeypatch.setenv("INSIGHTFLOW_IGNORE_CHOICES", "1")
    assert load_dataset_config("SALES_002", cfg_dir).columns["Region"].missing_policy == "fill_from_group"


def test_api_save_list_reset(client, cfg_dir):
    r = client.put("/api/datasets/SALES_002/choices/Sub_Category",
                   json={"settings": {"missing_policy": "fill_down", "group_by": ["Order_ID"], "fill_limit": 3}})
    assert r.status_code == 200 and r.json()["columns"]["Sub_Category"]["fill_limit"] == 3
    rules = client.get("/api/datasets/SALES_002/rules").json()
    assert rules["columns"]["Sub_Category"]["missing_policy"] == "fill_down"
    assert client.get("/api/datasets/SALES_002/choices").json()["file"] == "configs/choices/SALES_002.yaml"
    r = client.put("/api/datasets/SALES_002/choices/Sub_Category", json={"settings": None})
    assert r.json()["columns"] == {} and not (cfg_dir / "choices" / "SALES_002.yaml").exists()


def test_api_refuses_with_a_readable_reason(client):
    r = client.put("/api/datasets/SALES_002/choices/Product", json={"settings": {"missing_policy": "keep_and_flag"}})
    assert r.status_code == 400 and "not nullable" in r.json()["detail"]
    r = client.put("/api/datasets/SALES_002/choices/Nope", json={"settings": {"missing_policy": "quarantine"}})
    assert r.status_code == 400 and "unknown column" in r.json()["detail"]


def test_api_marks_counts_flags(client, tmp_path):
    src = tmp_path / "m.csv"
    src.write_text(HEADER + "\nIN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,999,0.1,20\n", encoding="utf-8")
    with open(src, "rb") as f:
        assert client.post("/api/run", data={"dataset_id": "SALES_002"}, files={"file": ("m.csv", f)}).status_code == 200
    assert client.get("/api/runs/SALES_002/marks").json()["marks"]
