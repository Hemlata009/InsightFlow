"""Gap 1: XML (defusedxml), fixed-width (pandas.read_fwf), merged cells + two-row headers, uncalculated formulas."""

import openpyxl
import pytest

from insightflow.ingestion import SOURCE_ROW, IngestionError, IngestOptions, read_file


def code_of(fn):
    with pytest.raises(IngestionError) as e:
        fn()
    return e.value.code


# ---------------- XML
def test_xml_records(tmp_path):
    p = tmp_path / "o.xml"
    p.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<orders>
  <order id="A1"><Product>Pen Set</Product><Qty>2</Qty><Sales>₹1,800</Sales></order>
  <order id="A2"><Product>Stapler</Product><Qty>3</Qty><customer><name>Asha</name><city>Pune</city></customer></order>
</orders>""", encoding="utf-8")
    r = read_file(p)
    assert r.metadata.columns[:4] == ["@id", "Product", "Qty", "Sales"]
    assert r.data.loc[0, "Sales"] == "₹1,800" and r.data.loc[1, "Sales"] == ""     # missing element -> blank
    assert r.data.loc[1, "customer.name"] == "Asha"                                  # nested element flattened


def test_xml_bomb_is_refused(tmp_path):
    p = tmp_path / "bomb.xml"
    p.write_text('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
                 '<rows><row><v>&b;</v></row></rows>', encoding="utf-8")
    assert code_of(lambda: read_file(p)) == "unsafe_xml"


def test_broken_xml(tmp_path):
    p = tmp_path / "b.xml"
    p.write_text("<rows><row><v>1</v></row>", encoding="utf-8")
    assert code_of(lambda: read_file(p)) == "corrupt_file"


# ---------------- fixed-width text
FWF = (
    "Order_ID  Product         Qty   Sales\n"
    "IN-1      Pen Set           2   180.00\n"
    "IN-2      Desk Organizer   10  6500.00\n"
    "\n"
    "IN-3      Stapler           1   300.00\n"
)


@pytest.mark.parametrize("name", ["report.fwf", "report.prn", "report.txt"])
def test_fixed_width(tmp_path, name):
    p = tmp_path / name
    p.write_text(FWF, encoding="utf-8")
    r = read_file(p)
    assert r.metadata.columns == ["Order_ID", "Product", "Qty", "Sales"]
    assert r.data["Product"].tolist() == ["Pen Set", "Desk Organizer", "Stapler"]
    assert r.data[SOURCE_ROW].tolist() == [2, 3, 5]
    if name.endswith(".txt"):
        assert any("fixed-width" in w for w in r.warnings)


# ---------------- merged cells and two-row headers
def _merged_workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Region", "Sales", None, "Profit", None])
    ws.append([None, "Q1", "Q2", "Q1", "Q2"])
    ws.append(["North", 100, 120, 10, 12])
    ws.append(["South", 90, 95, 8, 9])
    ws.append([None, 50, 60, 5, 6])          # region continues from the merged cell above
    ws.merge_cells("B1:C1")
    ws.merge_cells("D1:E1")
    ws.merge_cells("A1:A2")
    ws.merge_cells("A4:A5")                  # "South" spans two data rows
    wb.save(path)
    return path


def test_merged_cells_and_two_row_header(tmp_path):
    p = _merged_workbook(tmp_path / "m.xlsx")
    r = read_file(p, options=IngestOptions(header_rows=2))
    assert r.metadata.columns == ["Region", "Sales Q1", "Sales Q2", "Profit Q1", "Profit Q2"]
    assert r.data["Region"].tolist() == ["North", "South", "South"]     # merged data cell filled down
    assert any("merged" in w for w in r.warnings)


def test_merged_cells_without_header_option(tmp_path):
    r = read_file(_merged_workbook(tmp_path / "m.xlsx"))
    assert r.metadata.columns[:3] == ["Region", "Sales", "Sales__2"]   # repeated name made unique, not lost


# ---------------- formulas saved without results
def test_simple_formulas_are_calculated_others_set_aside(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Order_ID", "Qty", "Price", "Sales"])
    ws.append(["A0", 2, 100, "=B2*C2*(1-0.1)"])  # arithmetic only: calculated by InsightFlow
    ws.append(["A1", 2, 100, 200])
    ws.append(["A2", 3, 100, "=SUM(B4:C4)"])  # a function: not guessed -> set aside
    wb.save(tmp_path / "f.xlsx")
    r = read_file(tmp_path / "f.xlsx")
    assert r.metadata.rows == 2 and r.data.loc[0, "Sales"] == "180" and r.bad_rows[0]["source_row"] == 4
    assert any("calculated by InsightFlow" in w for w in r.warnings)
    assert "uncalculated formula" in r.bad_rows[0]["reason"] and any("never recalculated" in w for w in r.warnings)


def test_two_row_header_from_the_rule_book(tmp_path):
    """policies.header_rows: 2 joins the two header lines; works in normal AND chunked mode."""
    import shutil

    import pandas as pd
    import yaml

    from insightflow.config import CONFIG_DIR
    from insightflow.pipeline import run_phase1
    top = "Order,Order,Customer,Product,Category,Region,Quantity,Unit,Sales,Discount,Profit"
    sub = "ID,Date,ID,,,,,Price,,,"
    row = "IN-1,05/03/2025,C1,Pen Set,Office Supplies,North,2,100,180,0.1,20"
    p = tmp_path / "two.csv"
    p.write_text(top + "\n" + sub + "\n" + row + "\n" + row.replace("IN-1", "IN-2") + "\n", encoding="utf-8")
    for mode in ["never", "always"]:
        d = tmp_path / f"cfg_{mode}"
        shutil.copytree(CONFIG_DIR, d)
        f = d / "datasets" / "SALES_002.yaml"
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        data["policies"].update(header_rows=2, large_files=mode, chunk_rows=10)
        f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        res = run_phase1(p, "SALES_002", data_root=tmp_path / mode, config_dir=d)
        assert res["status"] == "completed", (mode, res["warnings"], res.get("error"))
        out = pd.read_csv(res["output_paths"]["cleaned"], encoding="utf-8-sig")
        assert out["Unit_Price"].tolist() == [100, 100] and out["source_row"].tolist() == [3, 4], mode
