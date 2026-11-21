"""SALES_003 "chaos": one deliberately unstructured file with (almost) every problem at once.

Every data row tests ONE case and the answer key says exactly what must happen to it:
  keep        -> in the cleaned output, with the listed values
  flag        -> kept, and flagged with the listed rule
  quarantine  -> set aside, reason contains the listed text
  duplicate   -> removed as a copy of an earlier row

    python -m harness run -- python -m scripts.sample_data.chaos
Writes data/sample/SALES_003/{chaos.csv, chaos.xlsx, answer_key.json}. Deterministic.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "sample" / "SALES_003"

# canonical column -> messy header used in the file
COLUMNS = [("Order_ID", " order_id"), ("Order_Date", "ORDER DATE"), ("Customer_ID", "Customer Id"),
           ("Product", "product"), ("Category", "Category "), ("Region", "region"), ("State", "STATE"),
           ("Quantity", "Qty"), ("Unit_Price", "Unit Price (INR)"), ("Sales", "Sales Amount"),
           ("Discount", "discount"), ("Profit", "Profit"), ("Segment", "segment"), ("Sub_Category", "Sub Category")]
EXTRA = ["Remarks", "", "Notes", "Notes"]          # unknown column, a column with no name, a duplicated name
HEADER = [h for _, h in COLUMNS] + EXTRA

BASE = {"Order_Date": "05/03/2025", "Product": "Pen Set", "Category": "Office Supplies", "Region": "North",
        "State": "Delhi", "Quantity": "2", "Unit_Price": "100", "Sales": "180", "Discount": "0.1", "Profit": "20",
        "Segment": "Consumer", "Sub_Category": "Writing"}
BIG = {"Quantity": "1000", "Unit_Price": "200", "Discount": "0.1", "Profit": "20000"}      # Sales = 180,000


def cases():
    """(id, description, overrides, expectation). Each produces one or more rows."""
    c = []

    def add(group, desc, expect, rows):
        c.append({"id": f"C{len(c) + 1:02d}", "group": group, "description": desc, "expect": expect, "rows": rows})

    one = lambda **o: [o]                                                     # noqa: E731
    k = lambda **v: {"outcome": "keep", "values": v}                         # noqa: E731
    q = lambda reason: {"outcome": "quarantine", "reason": reason}           # noqa: E731
    fx = lambda rule, **v: {"outcome": "flag", "rule": rule, "values": v}     # noqa: E731  kept + flagged
    rep_ = lambda **v: fx("repaired_from_formula", **v)                       # noqa: E731  proven repair
    # ---------------- numbers & money
    add("numbers", "rupee sign", k(Sales=180), one(Sales="₹180.00"))
    add("numbers", "Indian grouping", k(Sales=180000), one(**BIG, Sales="1,80,000.00"))
    add("numbers", "lakh short form", k(Sales=180000), one(**BIG, Sales="1.8 L"))
    add("numbers", "crore short form", k(Sales=180000), one(**BIG, Sales="0.018 Cr"))
    add("numbers", "thousand short form", k(Sales=180000), one(**BIG, Sales="180K"))
    add("numbers", "accounting negative", k(Profit=-1401.97), one(Profit="(1,401.97)"))
    add("numbers", "unicode minus", k(Profit=-20), one(Profit="−20"))
    add("numbers", "trailing minus", k(Profit=-20), one(Profit="20-"))
    add("numbers", "two minus markers: negative, flagged (user)", fx("double_minus_sign", Profit=-20), one(Profit="(20-)"))
    add("numbers", "percent", k(Discount=0.1), one(Discount="10%"))
    add("numbers", "percent with space", k(Discount=0.1), one(Discount="10 %"))
    add("numbers", "discount above 80%: repaired from formula", rep_(Discount=0.1), one(Discount="1.5"))
    add("numbers", "150 percent: repaired from formula", rep_(Discount=0.1), one(Discount="150%"))
    add("numbers", "Rs. prefix", k(Unit_Price=100), one(Unit_Price="Rs. 100"))
    add("numbers", "INR code before", k(Unit_Price=100), one(Unit_Price="INR 100"))
    add("numbers", "INR code after", k(Unit_Price=100), one(Unit_Price="100 INR"))
    add("numbers", "dollar sign in a rupee file: repaired", rep_(Unit_Price=100), one(Unit_Price="$100"))
    add("numbers", "US dollars: repaired", rep_(Unit_Price=100), one(Unit_Price="US$100"))
    add("numbers", "euros: repaired", rep_(Unit_Price=100), one(Unit_Price="€100"))
    add("numbers", "text instead of a price: repaired", rep_(Unit_Price=100), one(Unit_Price="abc"))
    add("numbers", "Excel error text: repaired", rep_(Unit_Price=100), one(Unit_Price="#VALUE!"))
    add("numbers", "infinity: repaired", rep_(Unit_Price=100), one(Unit_Price="inf"))
    add("numbers", "European number style: repaired", rep_(Unit_Price=100), one(Unit_Price="1.234,56"))
    add("numbers", "too many digits: repaired", rep_(Sales=180), one(Sales="12345678901234567"))
    add("numbers", "fractional quantity", q("not_a_whole_number"), one(Quantity="2.5", Sales="225"))
    add("numbers", "zero quantity", q("quantity_not_zero"), one(Quantity="0", Sales="0", Profit="0"))
    add("numbers", "negative quantity, positive sales (2 repairs fit: ambiguous)", q("return_sign_consistency"),
        one(Quantity="-999"))
    add("numbers", "valid return", k(Quantity=-2, Sales=-180, Profit=-20), one(Quantity="-2", Sales="-180", Profit="-20"))
    add("numbers", "quantity above 1000", q("less_than_or_equal_to(1000.0)"), one(Quantity="1,001", Sales="90090"))
    add("numbers", "sales doesn't match the formula", {"outcome": "flag", "rule": "sales_formula"}, one(Sales="500"))
    # ---------------- blanks and business rules
    add("blanks", "missing customer, same order has it (BR-3)", k(Customer_ID="C900"),
        [{"Order_ID": "CH-BR3", "Customer_ID": "C900", "Product": "Stapler", "_expect": "keep"},
         {"Order_ID": "CH-BR3", "Customer_ID": "NA"}])
    add("blanks", "missing customer, nothing to copy", {"outcome": "flag", "rule": "missing_value_no_group_value"},
        one(Customer_ID="-"))
    add("blanks", "missing region, same state known (BR-2)", k(Region="North"), one(Region=""))
    add("blanks", "missing region, state seen nowhere else", {"outcome": "flag", "rule": "missing_value_no_group_value"},
        one(Region="NULL", State="Goa"))
    add("blanks", "missing date, same order has it (BR-4)", k(Order_Date="2025-03-07"),
        [{"Order_ID": "CH-BR4", "Order_Date": "07/03/2025", "Product": "Stapler", "_expect": "keep"},
         {"Order_ID": "CH-BR4", "Order_Date": "N/A"}])
    add("blanks", "missing date, nothing to copy", q("missing_required:Order_Date"), one(Order_Date=""))
    add("blanks", "missing discount: derived", k(Discount=0.1), one(Discount="NA"))
    add("blanks", "missing sales: derived", k(Sales=180), one(Sales=""))
    add("blanks", "missing price: derived", k(Unit_Price=100), one(Unit_Price="-"))
    add("blanks", "two missing, can't derive", q("missing_not_derivable"), one(Discount="NA", Sales="NA"))
    add("blanks", "missing order id: temporary ID, flagged (user)", fx("placeholder_value"), one(Order_ID=""))
    add("blanks", "product given as '?'", q("missing_required:Product"), one(Product="?"))
    add("blanks", "order lines disagree on the customer: kept blank, flagged", fx("group_values_conflict", Customer_ID=""),
        [{"Order_ID": "CH-BR5", "Customer_ID": "C701", "_expect": "keep"},
         {"Order_ID": "CH-BR5", "Customer_ID": "C702", "Product": "Stapler", "_expect": "keep"},
         {"Order_ID": "CH-BR5", "Customer_ID": "NA", "Product": "Paper Ream"}])
    # ---------------- dates
    add("dates", "ISO date", k(Order_Date="2025-03-05"), one(Order_Date="2025-03-05"))
    add("dates", "month name", k(Order_Date="2025-03-05"), one(Order_Date="05-Mar-25"))
    add("dates", "Excel date number", k(Order_Date="2025-03-05"), one(Order_Date="45721"))
    add("dates", "Excel date number with time", k(Order_Date="2025-03-05"), one(Order_Date="45721.75"))
    add("dates", "two-digit year", k(Order_Date="2026-03-05"), one(Order_Date="05/03/26"))
    add("dates", "UTC time becomes the next day in India", k(Order_Date="2025-03-06"), one(Order_Date="2025-03-05T20:00:00Z"))
    add("dates", "date with time", k(Order_Date="2025-03-05"), one(Order_Date="05/03/2025 14:30"))
    add("dates", "IST in an Indian file = India Standard Time", k(Order_Date="2025-03-05"), one(Order_Date="2025-03-05 10:00 IST"))
    add("dates", "no year: most common year, flagged", fx("partial_date_completed:mode_year", Order_Date="2025-03-05"),
        one(Order_Date="05/03"))
    add("dates", "no day: 1st of the month, flagged", fx("partial_date_completed:first_of_month", Order_Date="2025-03-01"),
        one(Order_Date="Mar 2025"))
    add("dates", "impossible date", q("unrecognised_date"), one(Order_Date="31/02/2025"))
    add("dates", "real leap day, but before the business range", q("order_date_in_range"), one(Order_Date="29/02/2024"))
    add("dates", "year 2035", q("order_date_in_range"), one(Order_Date="19/02/2035"))
    add("dates", "Unix timestamp (UTC -> India)", k(Order_Date="2025-03-05"), one(Order_Date="1741132800"))
    add("dates", "compact date", k(Order_Date="2025-03-05"), one(Order_Date="20250305"))
    add("dates", "written date (dateparser)", k(Order_Date="2025-03-05"), one(Order_Date="5th March 2025"))
    add("dates", "date in Hindi (dateparser)", k(Order_Date="2025-03-05"), one(Order_Date="5 मार्च 2025"))
    # ---------------- text
    add("text", "spaces and small letters", k(Region="North"), one(Region="  north "))
    add("text", "capital letters", k(Region="North"), one(Region="NORTH"))
    add("text", "category in small letters", k(Category="Office Supplies"), one(Category="office supplies"))
    add("text", "region not allowed: replaced from the same state, flagged", fx("invalid_value_replaced", Region="North"),
        one(Region="Mars"))
    add("text", "messy product spacing", k(Product="Pen Set"), one(Product="  pen   set "))
    add("text", "invisible non-breaking space", k(Product="Pen Set"), one(Product="Pen Set"))
    add("text", "spreadsheet formula text kept as text", k(Product='=HYPERLINK("http://evil.example")'),
        one(Product='=HYPERLINK("http://evil.example")'))
    add("text", "leading zeros kept", k(Customer_ID="007"), one(Customer_ID="007"))
    add("text", "line break inside a cell (quoted)", k(Remarks="first line\nsecond line"),
        one(Remarks="first line\nsecond line"))
    # ---------------- duplicates and keys
    add("duplicates", "exact copy", {"outcome": "duplicate"}, [{"_expect": "keep"}, {"_same_as_previous": True}])
    add("duplicates", "copy hidden by spaces and capitals", {"outcome": "duplicate"},
        [{"_expect": "keep"}, {"_same_as_previous": True, "Region": " north ", "Product": "PEN SET "}])
    add("duplicates", "same order, different products (line items)", k(),
        [{"Order_ID": "CH-LINES", "_expect": "keep"}, {"Order_ID": "CH-LINES", "Product": "Stapler"}])
    add("duplicates", "same order and product, different numbers", {"outcome": "flag", "rule": "key_conflict"},
        [{"Order_ID": "CH-KEY", "_expect_flag": "key_conflict"},
         {"Order_ID": "CH-KEY", "Quantity": "3", "Sales": "270", "Profit": "30"}])
    return c


def _rows():
    """Expand cases into concrete rows (canonical values + extras), each tagged with its case and expectation."""
    out = []
    for n, case in enumerate(cases(), start=1):
        prev = None
        for j, ov in enumerate(case["rows"]):
            ov = dict(ov)
            if ov.pop("_same_as_previous", False):
                row = dict(prev)
                row.update({k: v for k, v in ov.items() if not k.startswith("_")})
            else:
                row = {**BASE, "Order_ID": f"CH-{n:03d}", "Customer_ID": f"C{n:03d}", "Remarks": case["id"], "": "",
                       "Notes": "", "Notes__2": ""}
                row.update({k: v for k, v in ov.items() if not k.startswith("_")})
            last = j == len(case["rows"]) - 1
            expect = {"outcome": ov["_expect"]} if "_expect" in ov else (
                {"outcome": "flag", "rule": ov["_expect_flag"]} if "_expect_flag" in ov else
                (case["expect"] if last else {"outcome": "keep"}))
            out.append((case, row, expect))
            prev = row
    out[3][1][""] = "x"        # one value in the column that has no header name
    return out


def _values(row):
    return [row[c] for c, _ in COLUMNS] + [row["Remarks"], row[""], row["Notes"], row["Notes__2"]]


def build(out_dir: Path = OUT) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _rows()
    key = {"dataset_id": "SALES_003", "description": "Chaos file: one row per problem", "cases": []}

    # ---------------- CSV: title lines, a blank line, messy header, blank lines between, broken rows
    buf = io.StringIO()
    line = 0

    def emit(text):
        nonlocal line
        buf.write(text)
        line += text.count("\n")

    def write_row(values):
        s = io.StringIO()
        csv.writer(s, lineterminator="\n").writerow(values)
        emit(s.getvalue())
        return line                         # the reader reports the line where the record ENDS

    emit("InsightFlow chaos export,,,\n")
    emit("Generated for testing; every row is one problem\n")
    emit("\n")
    write_row(HEADER)
    csv_rows = []
    for i, (case, row, expect) in enumerate(rows):
        if i in (10, 40):
            emit("\n")                      # blank lines in the middle
        csv_rows.append({"case": case["id"], "row": write_row(_values(row)), **expect})
    # broken rows (CSV only)
    emit("CH-RAGGED,05/03/2025,oops\n")
    csv_rows.append({"case": "R1", "row": line, "outcome": "quarantine", "reason": "unreadable_row"})
    emit(",".join(_values({**rows[0][1], "Order_ID": "CH-WIDE"})) + ",surprise,extra\n")
    csv_rows.append({"case": "R2", "row": line, "outcome": "flag", "rule": "extra_cells_overflow"})
    (out_dir / "chaos.csv").write_bytes(("﻿" + buf.getvalue()).encode("utf-8"))

    # ---------------- Excel: README sheet, hidden sheet, merged title, real numbers/dates, formula, error cell
    import openpyxl
    wb = openpyxl.Workbook()
    readme = wb.active
    readme.title = "README"
    readme.append(["This workbook is a test file. Data is on the 'Sales Data' sheet."])
    old = wb.create_sheet("Old export")
    old.append(HEADER)
    for i in range(150):
        old.append(_values({**rows[0][1], "Order_ID": f"OLD-{i}"}))
    old.sheet_state = "hidden"
    ws = wb.create_sheet("Sales Data")
    ws.append(["InsightFlow chaos export"])
    ws.merge_cells("A1:F1")
    ws.append(["Every row is one problem"])
    ws.append(HEADER)
    xlsx_rows = []
    r = 3
    for i, (case, row, expect) in enumerate(rows):
        if i == 20:
            ws.append([])
            r += 1
        values = _values(row)
        if case["id"] == "C01":                       # real numeric cells instead of text
            values[7], values[8] = 2, 100.0
        ws.append(values)
        r += 1
        if str(row["Product"]).startswith("="):   # in Excel a cell starting with "=" IS a formula (no result)
            expect = {"outcome": "quarantine", "reason": "uncalculated formula"}
        xlsx_rows.append({"case": case["id"], "row": r, **expect})
    real_date = _values({**rows[0][1], "Order_ID": "CH-XDATE", "Remarks": "X1"})
    real_date[1] = datetime(2025, 3, 5)                 # a real Excel date cell
    ws.append(real_date)
    r += 1
    xlsx_rows.append({"case": "X1", "row": r, "outcome": "keep", "values": {"Order_Date": "2025-03-05"}})
    formula = _values({**rows[0][1], "Order_ID": "CH-XFORMULA", "Remarks": "X2"})
    formula[9] = f"=H{r + 1}*I{r + 1}*(1-K{r + 1})"     # saved without a result
    ws.append(formula)
    r += 1
    xlsx_rows.append({"case": "X2", "row": r, "outcome": "keep", "values": {"Sales": 180}})
    err = _values({**rows[0][1], "Order_ID": "CH-XERROR", "Remarks": "X3"})
    err[8] = "#DIV/0!"
    ws.append(err)
    r += 1
    xlsx_rows.append({"case": "X3", "row": r, "outcome": "flag", "rule": "repaired_from_formula",
                      "values": {"Unit_Price": 100}})
    wb.properties.created = wb.properties.modified = datetime(2026, 1, 1)
    wb.save(out_dir / "chaos.xlsx")

    key["cases"] = [{k: v for k, v in c.items() if k != "rows"} for c in cases()] + [
        {"id": "R1", "group": "structure", "description": "row with too few fields", "expect": {"outcome": "quarantine"}},
        {"id": "R2", "group": "structure", "description": "row with too many fields: extras kept aside, flagged",
         "expect": {"outcome": "flag"}},
        {"id": "X1", "group": "excel", "description": "real Excel date cell", "expect": {"outcome": "keep"}},
        {"id": "X2", "group": "excel", "description": "formula without its result: calculated by InsightFlow",
         "expect": {"outcome": "keep"}},
        {"id": "X3", "group": "excel", "description": "#DIV/0! error cell: repaired from formula", "expect": {"outcome": "flag"}},
    ]
    key["files"] = {"chaos.csv": {"header_row": 4, "rows": csv_rows},
                    "chaos.xlsx": {"sheet": "Sales Data", "header_row": 3, "rows": xlsx_rows}}
    key["file_level"] = ["title lines above the header", "blank lines", "header names with spaces/case/aliases",
                         "a column with no name", "a duplicated column name", "an extra unknown column",
                         "UTF-8 with BOM", "Excel: README sheet first, hidden bigger sheet, merged title cell"]
    (out_dir / "answer_key.json").write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                             newline="\n")
    return key


if __name__ == "__main__":
    k = build()
    print(f"SALES_003: {len(k['cases'])} cases, csv rows {len(k['files']['chaos.csv']['rows'])}, "
          f"xlsx rows {len(k['files']['chaos.xlsx']['rows'])}")
