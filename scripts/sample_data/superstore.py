"""SALES_001: real Superstore data (US, USD, month/day/year) mapped to the InsightFlow schema."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.fetch_superstore import SHA256, TARGET, URL

from .common import COLUMNS, make_messy, write_outputs

DATASET_ID = "SALES_001"
LOCALE = "en_US"
SEED = 1001

# Messy files keep Superstore's original header names.
HEADER_MAP = {
    "Order_ID": "Order ID", "Order_Date": "Order Date", "Customer_ID": "Customer ID",
    "Product": "Product Name", "Category": "Category", "Region": "Region", "Quantity": "Quantity",
    "Unit_Price": "Unit Price", "Sales": "Sales", "Discount": "Discount", "Profit": "Profit",
    "Sub_Category": "Sub-Category", "Segment": "Segment", "State": "State",
}


def load_raw(path: Path = TARGET) -> pd.DataFrame:
    return pd.read_csv(path, encoding="cp1252", dtype={"Postal Code": str})


def build_truth(raw: pd.DataFrame) -> pd.DataFrame:
    t = pd.DataFrame({
        "source_row_id": raw["Row ID"].astype(int),
        "Order_ID": raw["Order ID"],
        "Order_Date": pd.to_datetime(raw["Order Date"], format="%m/%d/%Y"),
        "Customer_ID": raw["Customer ID"],
        "Product": raw["Product Name"],
        "Category": raw["Category"],
        "Region": raw["Region"],
        "Quantity": raw["Quantity"].astype(int),
        # Superstore has no unit price; derive it: Sales = Qty * Unit_Price * (1 - Discount)
        "Unit_Price": (raw["Sales"] / (raw["Quantity"] * (1 - raw["Discount"]))).round(4),
        "Sales": raw["Sales"],
        "Discount": raw["Discount"],
        "Profit": raw["Profit"],
        "Sub_Category": raw["Sub-Category"],
        "Segment": raw["Segment"],
        "State": raw["State"],
    })
    return t[COLUMNS].reset_index(drop=True)


def natural_issues(raw: pd.DataFrame) -> list[dict]:
    """Problems that already exist in the real file (found by inspection, not planted)."""
    dup_rows = int(raw.drop(columns="Row ID").duplicated().sum())
    dup_keys = int(raw.duplicated(["Order ID", "Product ID"]).sum())
    short_zip = int((raw["Postal Code"].str.len() < 5).sum())
    nbsp = int(raw.select_dtypes(include=["object", "string"]).apply(
        lambda c: c.astype("string").str.contains(" ", regex=False)).any(axis=1).sum())
    return [
        {"issue_type": "encoding", "detail": "Raw file is cp1252 (Windows-1252), not UTF-8",
         "expected_action": "detect_encoding"},
        {"issue_type": "exact_duplicate", "count": dup_rows,
         "detail": "Fully identical rows apart from Row ID (kept in truth: may be genuine)",
         "expected_action": "flag_for_review"},
        {"issue_type": "repeated_key", "count": dup_keys,
         "detail": "Same Order ID + Product ID appears more than once",
         "expected_action": "flag_for_review"},
        {"issue_type": "leading_zero_lost", "count": short_zip,
         "detail": "Postal codes with fewer than 5 digits (e.g. 1040 should be 01040); column excluded from schema",
         "expected_action": "read_ids_as_text"},
        {"issue_type": "non_breaking_space", "count": nbsp,
         "detail": "Invisible non-breaking spaces (U+00A0) inside text, e.g. product names; truth keeps them",
         "expected_action": "normalize_whitespace"},
    ]


def build(out_dir: Path) -> dict:
    raw = load_raw()
    truth = build_truth(raw)
    messy, issues = make_messy(truth, LOCALE, SEED)
    return write_outputs(
        out_dir, DATASET_ID, truth, messy, issues,
        locale=LOCALE, header_map=HEADER_MAP, csv_encoding="cp1252", csv_sep=",",
        source={"name": "Tableau Sample - Superstore", "url": URL, "sha256": SHA256,
                "note": "Real data; not committed to git. Fetch with scripts.fetch_superstore."},
        natural_issues=natural_issues(raw),
        stories=[{"story": "real_patterns",
                  "detail": "Real seasonality (Q4 peaks) and loss-making high-discount sales"}],
    )
