"""Example plugin: extra sales sanity checks. Enable with `plugins: [plugins.sales_sanity]` in a dataset config.

Domain names are fine here: plugins are business add-ons, not the generic engine.
"""

from insightflow.hooks import hookimpl
from insightflow.ingestion import SOURCE_ROW


@hookimpl
def extra_checks(data, cfg):
    """Flag sales where the profit is larger than the sale itself (usually a data-entry error)."""
    if not {"Profit", "Sales"} <= set(data.columns):
        return []
    bad = data[(data["Sales"] > 0) & (data["Profit"] > data["Sales"])]
    return [{"source_row": int(r[SOURCE_ROW]), "check": "profit_exceeds_sales", "column": "Profit",
             "value": float(r["Profit"]), "severity": "flag"} for _, r in bad.iterrows()]
