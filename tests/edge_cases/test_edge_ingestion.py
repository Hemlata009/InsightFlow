"""Edge-case group 1: file formats and reading."""

import json
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from insightflow.ingestion import SOURCE_ROW, IngestionError, IngestOptions, read_file

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"


def code_of(fn):
    with pytest.raises(IngestionError) as e:
        fn()
    return e.value.code


# ---------------- JSON / JSON Lines / nested
def test_json_array_of_records(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps([{"Order ID": "A1", "Qty": 2, "Price": 1.5, "Paid": True},
                             {"Order ID": "A2", "Qty": 3, "Price": None, "Paid": False}]), encoding="utf-8")
    r = read_file(p)
    assert r.metadata.columns == ["Order ID", "Qty", "Price", "Paid"]
    assert r.data.loc[0].drop(SOURCE_ROW).tolist() == ["A1", "2", "1.5", "TRUE"]
    assert r.data.loc[1, "Price"] == ""                       # null -> blank


def test_json_records_under_one_key(tmp_path):
    p = tmp_path / "w.json"
    p.write_text(json.dumps({"meta": {"v": 1}, "data": [{"a": 1, "b": 2}]}), encoding="utf-8")
    r = read_file(p)
    assert r.metadata.columns == ["a", "b"] and any("'data' key" in w for w in r.warnings)


def test_json_lines_with_a_broken_line(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text('{"a": 1, "b": "x"}\n\n{"a": 2, "b": "y"}\nnot json\n{"a": 3}\n', encoding="utf-8")
    r = read_file(p)
    assert list(r.data[SOURCE_ROW]) == [1, 3, 5]             # file line numbers
    assert r.data.loc[2, "b"] == ""                           # missing key -> blank
    assert [b["source_row"] for b in r.bad_rows] == [4]       # never silently dropped


def test_nested_json_flattened_lists_kept_as_text(tmp_path):
    p = tmp_path / "n.json"
    p.write_text(json.dumps([{"id": 1, "customer": {"id": "C1", "city": "Pune"}, "tags": ["a", "b"]}]),
                 encoding="utf-8")
    r = read_file(p)
    assert r.metadata.columns == ["id", "tags", "customer.id", "customer.city"]
    assert r.data.loc[0, "tags"] == '["a", "b"]'
    assert any("hold lists" in w for w in r.warnings) and any("flattened" in w for w in r.warnings)


@pytest.mark.parametrize("content, code", [("{\"a\": 1}", "unsupported_json"), ("[1, 2]", "unsupported_json"),
                                           ("[]", "no_data_rows")])
def test_bad_json_shapes(tmp_path, content, code):
    p = tmp_path / "b.json"
    p.write_text(content, encoding="utf-8")
    assert code_of(lambda: read_file(p)) == code


# ---------------- Parquet
def test_parquet_round_trip_matches_csv(tmp_path):
    src = SAMPLE / "SALES_002" / "sales_truth.csv"
    df = pd.read_csv(src, dtype=str)
    p = tmp_path / "t.parquet"
    df.to_parquet(p, index=False)
    r = read_file(p)
    assert r.metadata.format == "parquet" and r.metadata.rows == len(df)
    assert r.data.drop(columns=SOURCE_ROW).reset_index(drop=True).astype(str).equals(df.astype(str))


def test_parquet_typed_values_become_text(tmp_path):
    p = tmp_path / "typed.parquet"
    pd.DataFrame({"d": pd.to_datetime(["2025-03-05"]), "n": [3.0], "i": [7]}).to_parquet(p, index=False)
    r = read_file(p)
    assert r.data.loc[0, ["d", "n", "i"]].tolist() == ["2025-03-05", "3", "7"]


def test_fake_parquet(tmp_path):
    p = tmp_path / "f.parquet"
    p.write_text("a,b\n1,2\n")
    assert code_of(lambda: read_file(p)) == "signature_mismatch"


# ---------------- encodings and odd text files
def test_utf16_excel_unicode_text_export(tmp_path):
    p = tmp_path / "u.txt"
    p.write_bytes("Order ID\tCity\nA1\tMünchen\nA2\tಬೆಂಗಳೂರು\n".encode("utf-16"))   # Excel "Unicode Text"
    r = read_file(p)
    assert r.metadata.encoding == "utf-16" and r.metadata.delimiter == "\t"
    assert list(r.data["City"]) == ["München", "ಬೆಂಗಳೂರು"]


def test_quoted_newline_inside_a_field(tmp_path):
    p = tmp_path / "q.csv"
    p.write_bytes(b'id,note\n1,"line one\nline two"\n2,ok\n')      # exact bytes (no Windows \r\n)
    r = read_file(p)
    assert r.data.loc[0, "note"] == "line one\nline two" and r.metadata.rows == 2
    assert list(r.data[SOURCE_ROW]) == [3, 4]                 # line where each record ends


def test_tsv_extension(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text("a\tb\n1\t2\n", encoding="utf-8")
    assert read_file(p).metadata.delimiter == "\t"


# ---------------- Excel specifics
def test_hidden_sheet_ignored(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["a", "b"])
    ws.append([1, 2])
    big = wb.create_sheet("Old_backup")                        # bigger, but hidden
    big.append(["x", "y", "z"])
    for i in range(49):
        big.append([i, i, i])
    big.sheet_state = "hidden"
    p = tmp_path / "h.xlsx"
    wb.save(p)
    r = read_file(p)
    assert r.metadata.sheet_name == "Data" and any("hidden" in w for w in r.warnings)
    assert read_file(p, options=IngestOptions(sheet="Old_backup")).metadata.rows == 49   # still reachable


def test_excel_error_cells_are_kept_as_text(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["id", "price"])
    ws.append(["A1", "#DIV/0!"])
    p = tmp_path / "e.xlsx"
    wb.save(p)
    assert read_file(p).data.loc[0, "price"] == "#DIV/0!"


# ---------------- memory guard
def test_file_too_big_for_free_ram_is_refused(tmp_path, monkeypatch):
    import psutil

    class Fake:
        available = 100 * 2**20                                   # pretend only 100 MB is free
    monkeypatch.setattr(psutil, "virtual_memory", lambda: Fake)
    p = tmp_path / "big.csv"
    p.write_text("a,b\n" + "1,2\n" * 2000)
    assert read_file(p).metadata.rows == 2000                   # tiny file: never refused, even when RAM is low
    assert code_of(lambda: read_file(p, options=IngestOptions(min_checked_mb=0))) == "insufficient_memory"
    assert read_file(p, options=IngestOptions(check_memory=False, min_checked_mb=0)).metadata.rows == 2000
