"""Priority 2: "datetime" columns keep the time of day; "date" columns keep only the day (unchanged)."""

import shutil

import pandas as pd
import pytest
import yaml

from insightflow.config import CONFIG_DIR, ColumnSpec, load_dataset_config
from insightflow.ingestion import SOURCE_ROW, read_file
from insightflow.normalization import normalize, parse_dates
from insightflow.pipeline import run_phase1
from insightflow.profiling import profile

IN = load_dataset_config("SALES_002")       # Asia/Kolkata, DMY


def dt(values, keep_time=True, cfg=IN):
    d, rule, reason = parse_dates(pd.Series(values, dtype="string"), cfg, keep_time=keep_time)
    return [None if pd.isna(x) else str(x) for x in d], list(rule), list(reason)


@pytest.mark.parametrize("value, expected", [
    ("2025-03-05 14:30:00", "2025-03-05 14:30:00"),
    ("2025-03-05T14:30", "2025-03-05 14:30:00"),
    ("05/03/2025 14:30", "2025-03-05 14:30:00"),           # locale format + time
    ("2025-03-05T20:00:00Z", "2025-03-06 01:30:00"),        # UTC -> IST, time kept
    ("2025-03-05T20:00:00+05:30", "2025-03-05 20:00:00"),
    ("45746.75", "2025-03-30 18:00:00"),                     # Excel serial with time fraction
    ("05/03/2025", "2025-03-05 00:00:00"),                   # no time given -> midnight
])
def test_datetime_keeps_time(value, expected):
    assert dt([value])[0] == [expected]


def test_date_type_still_drops_time():
    d, rule, _ = dt(["2025-03-05 14:30:00", "05/03/2025 14:30"], keep_time=False)
    assert d == ["2025-03-05 00:00:00"] * 2 and set(rule) == {"datetime_time_dropped"}


def test_unix_milliseconds_keep_time():
    c = IN.model_copy(deep=True)
    c.policies.unix_timestamps = True
    assert dt(["1741185000000"], cfg=c)[0] == ["2025-03-05 20:00:00"]     # 14:30 UTC = 20:00 in India


def _with_ship_time(tmp_path):
    d = tmp_path / "cfg"
    shutil.copytree(CONFIG_DIR, d)
    f = d / "domains" / "sales.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    data["columns"]["Ship_Time"] = {"type": "datetime", "aliases": ["ship_time", "shipped_at"]}
    data["rules"]["ship_time_in_range"] = {"kind": "date_range", "severity": "quarantine",
                                           "params": {"column": "Ship_Time"}}
    f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return d


HEADER = "Order_ID,Order_Date,Customer_ID,Product,Category,Region,Quantity,Unit_Price,Sales,Discount,Profit,Shipped At"
ROW = "IN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,180,0.1,20,{t}"


def test_pipeline_outputs_time_and_is_idempotent(tmp_path):
    cfg_dir = _with_ship_time(tmp_path)
    p = tmp_path / "t.csv"
    p.write_text(HEADER + "\n" + ROW.format(t="2025-03-05T20:00:00Z") + "\n" +
                 ROW.format(t="30/06/2026 23:59").replace("IN-1", "IN-2") + "\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "d", config_dir=cfg_dir)
    out = pd.read_csv(res["output_paths"]["cleaned"], encoding="utf-8-sig", dtype=str)
    assert out["Ship_Time"].tolist() == ["2025-03-06 01:30:00", "2026-06-30 23:59:00"]   # last day, 23:59: inside range
    assert out["Order_Date"].tolist() == ["2025-03-05", "2025-03-05"]                    # date column unchanged
    again = run_phase1(res["output_paths"]["cleaned"], "SALES_002", data_root=tmp_path / "d2", config_dir=cfg_dir)
    out2 = pd.read_csv(again["output_paths"]["cleaned"], encoding="utf-8-sig", dtype=str)
    assert out2["Ship_Time"].tolist() == out["Ship_Time"].tolist() and again["rows_quarantined"] == 0


def test_profiler_accepts_datetime_text(tmp_path):
    cfg = load_dataset_config("SALES_002", _with_ship_time(tmp_path))
    p = tmp_path / "t.csv"
    p.write_text(HEADER + "\n" + ROW.format(t="05/03/2025 14:30") + "\n" +
                 ROW.format(t="2025-03-05T20:00:00+05:30").replace("IN-1", "IN-2") + "\n", encoding="utf-8")
    rep = profile(read_file(p, known_headers=set(cfg.header_map())).data, cfg)
    col = next(c for c in rep["columns"].values() if c["canonical"] == "Ship_Time")
    assert col["expected_type"] == "datetime" and col["type_mismatch"] == 0


def test_change_log_shows_time_values():
    cfg = IN.model_copy(deep=True)
    cfg.columns["Ship_Time"] = ColumnSpec(name="Ship_Time", type="datetime", aliases=["ship_time"])
    df = pd.DataFrame({"ship_time": ["2025-03-05T20:00:00Z"]}, dtype="string")
    df.insert(0, SOURCE_ROW, [2])
    n = normalize(df, cfg)
    c = next(c for c in n.changes if c["column"] == "Ship_Time")
    assert c["rule"] == "date:timezone_converted" and c["new"] == "2025-03-06 01:30:00"
