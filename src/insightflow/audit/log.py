"""One standard shape for every audit-log entry, so any value can be traced back to its source row.

Every entry in cleaning_log.json has:
    seq         1, 2, 3 ... in the order things happened
    run_id      which pipeline run
    kind        change | issue | flag | rejection | plugin_change
    stage       ingest | normalize | clean | validate | plugin
    rule        what did it (e.g. number:magnitude_suffix, derived, rule:order_date_in_range)
    source_row  row (line) in the ORIGINAL file
    column      column, or null for whole-row events (duplicates)
    old, new    value before / after (rejections and issues: the offending value in `old`)
    severity    quarantine | flag | null
    detail      extra explanation
"""

from __future__ import annotations

KINDS = ("change", "issue", "flag", "rejection", "plugin_change")
FIELDS = ("seq", "run_id", "kind", "stage", "rule", "source_row", "column", "old", "new", "severity", "detail")


def _kind(e: dict) -> str:
    if e.get("stage") == "plugin":
        return "plugin_change"
    if "flag" in e:
        return "flag"
    if "check" in e:
        return "rejection" if e.get("severity") == "quarantine" else "flag"
    if "reason" in e and "rule" not in e:
        return "issue"
    return "change"


def standard_entry(e: dict, seq: int, run_id: str) -> dict:
    kind = _kind(e)
    out = {
        "seq": seq, "run_id": run_id, "kind": kind, "stage": e.get("stage"),
        "rule": e.get("rule") or e.get("check") or e.get("flag") or (f"unconvertible:{e['reason']}" if "reason" in e else None),
        "source_row": e.get("source_row"), "column": e.get("column"),
        "old": e.get("old", e.get("value")), "new": e.get("new"),
        "severity": e.get("severity") or ("quarantine" if kind == "issue" else "flag" if kind == "flag" else None),
        "detail": e.get("detail"),
    }
    return out


class AuditLog:
    """Collects entries in order and gives each one the standard shape (works for streaming too)."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.seq = 0

    def standardize(self, entries) -> list[dict]:
        out = []
        for e in entries:
            self.seq += 1
            out.append(standard_entry(e, self.seq, self.run_id))
        return out


def summarize(entries: list[dict]) -> dict:
    """Counts by kind and by rule, for the quality report."""
    by_kind: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for e in entries:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
        by_rule[e["rule"] or "other"] = by_rule.get(e["rule"] or "other", 0) + 1
    return {"entries": len(entries), "by_kind": dict(sorted(by_kind.items())), "by_rule": dict(sorted(by_rule.items()))}


def trace(entries: list[dict], source_row: int) -> list[dict]:
    """Everything that happened to one original row, in order."""
    return sorted((e for e in entries if e.get("source_row") == source_row), key=lambda e: e["seq"])
