"""Step 3 tests: the safe reader handles real files and every ingestion edge case in the backlog."""

import json
import zipfile
from pathlib import Path

import openpyxl
import pytest

from insightflow.config import load_dataset_config
from insightflow.ingestion import (SOURCE_ROW, FileRegistry, IngestionError, IngestOptions,
                                   file_sha256, read_file)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


def known(ds):
    return set(load_dataset_config(ds).header_map())


def write(path, text, encoding="utf-8"):
    path.write_bytes(text.encode(encoding))
    return path


def xlsx(path, sheets: dict):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


def code_of(fn):
    with pytest.raises(IngestionError) as e:
        fn()
    return e.value.code


# ---------------------------------------------------------------- real sample files
def test_reads_sales_002_csv():
    r = read_file(SAMPLE / "SALES_002" / "sales_messy.csv", known_headers=known("SALES_002"))
    key = json.loads((SAMPLE / "SALES_002" / "answer_key.json").read_text(encoding="utf-8"))
    m = r.metadata
    assert (m.encoding, m.delimiter, m.header_row) == ("utf-8-sig", ";", 1)
    assert m.rows == key["rows"]["messy"] and len(m.columns) == 14
    assert m.columns[0] == " order_id"                       # headers are NOT renamed here
    assert r.data["Sales Amount"].str.startswith("₹").any()   # rupee sign decoded correctly
    assert r.bad_rows == []


def test_reads_sales_002_excel_and_matches_csv():
    k = known("SALES_002")
    x = read_file(SAMPLE / "SALES_002" / "sales_messy.xlsx", known_headers=k)
    c = read_file(SAMPLE / "SALES_002" / "sales_messy.csv", known_headers=k)
    assert x.metadata.sheet_name == "Sales" and x.metadata.header_row == 3
    assert any("2 sheets" in w for w in x.warnings)
    assert x.data.drop(columns=SOURCE_ROW).equals(c.data.drop(columns=SOURCE_ROW))


def test_reads_sales_001_cp1252():
    p = SAMPLE / "SALES_001" / "sales_messy.csv"
    if not p.exists():
        pytest.skip("SALES_001 not built")
    r = read_file(p, known_headers=known("SALES_001"))
    assert r.metadata.encoding == "cp1252" and r.metadata.delimiter == ","
    assert r.metadata.rows == 10074


def test_source_row_points_at_file_line(tmp_path):
    p = write(tmp_path / "a.csv", "title line\n\nid,name\n1,a\n\n2,b\n")
    r = read_file(p)
    assert r.metadata.header_row == 3
    assert list(r.data[SOURCE_ROW]) == [4, 6]
    assert any("blank row" in w for w in r.warnings)


def test_raw_file_is_not_modified():
    p = SAMPLE / "SALES_002" / "sales_messy.csv"
    before, mtime = file_sha256(p), p.stat().st_mtime_ns
    r = read_file(p)
    assert file_sha256(p) == before == r.metadata.sha256 and p.stat().st_mtime_ns == mtime


# ---------------------------------------------------------------- encodings & delimiters
@pytest.mark.parametrize("enc, expected", [("utf-8", "utf-8"), ("utf-8-sig", "utf-8-sig"), ("cp1252", "cp1252")])
def test_encodings(tmp_path, enc, expected):
    p = write(tmp_path / "e.csv", "name,city\nMüller,Café\nZoë,São Paulo\n", enc)
    r = read_file(p)
    assert r.metadata.encoding == expected
    assert list(r.data["name"]) == ["Müller", "Zoë"]


@pytest.mark.parametrize("sep", [",", ";", "\t", "|"])
def test_delimiters(tmp_path, sep):
    rows = [["id", "amount", "note"], ["1", "1,00,000", "a"], ["2", "2,500", "b"]]
    text = "\n".join(sep.join(f'"{c}"' if "," in c and sep == "," else c for c in r) for r in rows)
    r = read_file(write(tmp_path / "d.csv", text))
    assert r.metadata.delimiter == sep
    assert list(r.data["amount"]) == ["1,00,000", "2,500"]


def test_forced_delimiter_and_encoding(tmp_path):
    p = write(tmp_path / "f.csv", "a;b\n1;2\n", "cp1252")
    r = read_file(p, options=IngestOptions(delimiter=";", encoding="cp1252"))
    assert r.metadata.delimiter == ";" and r.metadata.encoding == "cp1252"


# ---------------------------------------------------------------- headers & columns
def test_duplicate_and_blank_headers(tmp_path):
    r = read_file(write(tmp_path / "h.csv", "id,name,name,\n1,a,b,c\n"))
    assert r.metadata.columns == ["id", "name", "name__2", "unnamed_4"]
    assert sum("duplicate" in w or "no header" in w for w in r.warnings) == 2


def test_leading_zeros_kept(tmp_path):
    r = read_file(write(tmp_path / "z.csv", "zip,id\n01040,007\n"))
    assert r.data.loc[0, "zip"] == "01040" and r.data.loc[0, "id"] == "007"


def test_known_headers_find_header_below_numeric_title(tmp_path):
    p = write(tmp_path / "k.csv", "2026,report,v1\nQty,Sales Amount,region\n3,100,North\n")
    r = read_file(p, known_headers=known("SALES_002"))
    assert r.metadata.header_row == 2


def test_no_header_found(tmp_path):
    p = write(tmp_path / "n.csv", "1,2,3\n4,5,6\n")
    assert code_of(lambda: read_file(p)) == "no_header_found"


def test_ragged_rows_set_aside_not_dropped(tmp_path):
    r = read_file(write(tmp_path / "r.csv", "a,b,c\n1,2,3\n4,5\n6,7,8,9\n10,11,12,,\n"))
    assert r.metadata.rows == 2                                   # rows 2 and 5 (trailing empties ok)
    assert [b["source_row"] for b in r.bad_rows] == [3, 4]


# ---------------------------------------------------------------- Excel specifics
def test_excel_multiple_sheets_auto_pick(tmp_path):
    p = xlsx(tmp_path / "m.xlsx", {"Readme": [["Read me first"]],
                                   "Data": [["Order ID", "Qty"], ["A1", 2], ["A2", 3.0]]})
    r = read_file(p)
    assert r.metadata.sheet_name == "Data" and r.metadata.sheet_names == ["Readme", "Data"]
    assert list(r.data["Qty"]) == ["2", "3"]


def test_excel_forced_and_missing_sheet(tmp_path):
    p = xlsx(tmp_path / "s.xlsx", {"A": [["x", "y"], [1, 2]], "B": [["p", "q"], [3, 4]]})
    assert read_file(p, options=IngestOptions(sheet="B")).metadata.columns == ["p", "q"]
    assert code_of(lambda: read_file(p, options=IngestOptions(sheet="Z"))) == "sheet_not_found"


def test_excel_empty_sheet(tmp_path):
    p = xlsx(tmp_path / "e.xlsx", {"Only": []})
    assert code_of(lambda: read_file(p)) == "empty_sheet"


def test_excel_dates_become_iso_text(tmp_path):
    from datetime import datetime
    p = xlsx(tmp_path / "d.xlsx", {"S": [["id", "when"], ["1", datetime(2026, 3, 5)]]})
    assert read_file(p).data.loc[0, "when"] == "2026-03-05"


# ---------------------------------------------------------------- bad files
def test_empty_and_blank_files(tmp_path):
    assert code_of(lambda: read_file(write(tmp_path / "e.csv", ""))) == "empty_file"
    assert code_of(lambda: read_file(write(tmp_path / "b.csv", "  \n\n "))) == "empty_file"


def test_header_only(tmp_path):
    assert code_of(lambda: read_file(write(tmp_path / "h.csv", "a,b,c\n"))) == "no_data_rows"


def test_not_found_and_unsupported(tmp_path):
    assert code_of(lambda: read_file(tmp_path / "missing.csv")) == "not_found"
    assert code_of(lambda: read_file(write(tmp_path / "x.xml", "<a/>"))) == "unsupported_format"


def test_excel_renamed_to_csv(tmp_path):
    src = xlsx(tmp_path / "real.xlsx", {"S": [["a", "b"], [1, 2]]})
    fake = tmp_path / "fake.csv"
    fake.write_bytes(src.read_bytes())
    assert code_of(lambda: read_file(fake)) == "signature_mismatch"


def test_text_renamed_to_xlsx(tmp_path):
    assert code_of(lambda: read_file(write(tmp_path / "t.xlsx", "a,b\n1,2\n"))) == "signature_mismatch"


def test_corrupt_excel(tmp_path):
    good = xlsx(tmp_path / "g.xlsx", {"S": [["a", "b"], [1, 2]]}).read_bytes()
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(good[: len(good) // 2])                       # truncated zip
    assert code_of(lambda: read_file(bad)) == "corrupt_file"
    z = tmp_path / "z.xlsx"
    with zipfile.ZipFile(z, "w") as f:                            # a zip, but not a workbook
        f.writestr("hello.txt", "hi")
    assert code_of(lambda: read_file(z)) == "corrupt_file"


def test_password_protected_and_legacy_xls(tmp_path):
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 500
    enc = tmp_path / "locked.xlsx"
    enc.write_bytes(ole + "EncryptedPackage".encode("utf-16-le"))
    assert code_of(lambda: read_file(enc)) == "encrypted_file"
    old = tmp_path / "old.xlsx"
    old.write_bytes(ole)
    assert code_of(lambda: read_file(old)) == "unsupported_format"


def test_too_large(tmp_path):
    p = write(tmp_path / "big.csv", "a,b\n" + "1,2\n" * 1000)
    assert code_of(lambda: read_file(p, options=IngestOptions(max_file_mb=0.001))) == "too_large"


# ---------------------------------------------------------------- repeated uploads
def test_registry_detects_same_file_twice(tmp_path):
    p = write(tmp_path / "a.csv", "a,b\n1,2\n")
    copy = write(tmp_path / "renamed_copy.csv", "a,b\n1,2\n")
    reg = FileRegistry(tmp_path / "registry.json")
    new1, _ = reg.register(read_file(p).metadata, "DS1")
    new2, entry = reg.register(read_file(copy).metadata, "DS1")
    assert new1 is True and new2 is False
    assert entry["file_name"] == "a.csv" and entry["times_seen"] == 2
