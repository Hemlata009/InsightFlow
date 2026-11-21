"""Add-on steps ("hooks") using pluggy (github.com/pytest-dev/pluggy, MIT): the plugin system pytest uses.

A plugin is a Python module listed in the dataset config (`plugins: [plugins.my_rules]`) that defines one
or more of these functions, marked with @hookimpl:

    after_ingest(data, cfg)     -> DataFrame | None    raw text table, right after reading
    after_normalize(data, cfg)  -> DataFrame | None    typed table, after standardizing
    after_clean(data, cfg)      -> DataFrame | None    after cleaning, before validation
    extra_checks(data, cfg)     -> list[dict]          extra rule failures:
                                   {"source_row", "check", "column", "value", "severity": "flag"|"quarantine"}

Safety: a plugin may change values but may NOT add, drop or re-number rows; that raises PluginError
and the run fails with code "plugin_error" (nothing half-written).
"""

from __future__ import annotations

import importlib
import re

import pandas as pd
import pluggy

from insightflow.ingestion import SOURCE_ROW

PROJECT = "insightflow"
hookspec = pluggy.HookspecMarker(PROJECT)
hookimpl = pluggy.HookimplMarker(PROJECT)
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
TRANSFORMS = ("after_ingest", "after_normalize", "after_clean")


class PluginError(RuntimeError):
    pass


class Spec:
    @hookspec
    def after_ingest(self, data, cfg):
        """Return a modified copy of the raw table (same rows), or None."""

    @hookspec
    def after_normalize(self, data, cfg):
        """Return a modified copy of the standardized table (same rows), or None."""

    @hookspec
    def after_clean(self, data, cfg):
        """Return a modified copy of the cleaned table (same rows), or None."""

    @hookspec
    def extra_checks(self, data, cfg):
        """Return a list of failure dicts (see module docstring)."""

    @hookspec(firstresult=True)
    def resolve_partial_date(self, column, text, parts, row, record, cfg):
        """Complete an incomplete date your own way (policy 'plugin'). `parts` is {'kind': 'missing_day',
        'month', 'year'} or {'kind': 'missing_year', 'day', 'month'}. Return a date, or None to set the row aside."""


def load_plugins(names: list[str]) -> pluggy.PluginManager:
    pm = pluggy.PluginManager(PROJECT)
    pm.add_hookspecs(Spec)
    for name in names:
        if not _NAME.match(name):
            raise PluginError(f"invalid plugin name {name!r}")
        try:
            module = importlib.import_module(name)
        except ImportError as e:
            raise PluginError(f"plugin {name!r} could not be imported: {e}") from e
        pm.register(module, name=name)
    return pm


def run_transform(pm: pluggy.PluginManager, hook: str, data: pd.DataFrame, cfg, log: list[dict]) -> pd.DataFrame:
    """Call every plugin's `hook` in turn, each on the previous plugin's output (a chain)."""
    for impl in getattr(pm.hook, hook).get_hookimpls():
        name = impl.plugin_name
        try:
            out = impl.function(data=data.copy(), cfg=cfg)
        except Exception as e:  # noqa: BLE001 - any plugin failure stops the run cleanly
            raise PluginError(f"plugin {name!r} failed in {hook}: {e}") from e
        if out is None:
            continue
        if not isinstance(out, pd.DataFrame):
            raise PluginError(f"plugin {name!r} {hook} must return a DataFrame or None")
        if SOURCE_ROW in data and (SOURCE_ROW not in out or list(out[SOURCE_ROW]) != list(data[SOURCE_ROW])):
            raise PluginError(f"plugin {name!r} {hook} added, dropped or reordered rows; that is not allowed")
        log.extend(cell_changes(data, out, f"{name}.{hook}"))
        data = out
    return data


def run_checks(pm: pluggy.PluginManager, data: pd.DataFrame, cfg) -> list[dict]:
    failures = []
    for impl in pm.hook.extra_checks.get_hookimpls():
        try:
            found = impl.function(data=data.copy(), cfg=cfg) or []
        except Exception as e:  # noqa: BLE001
            raise PluginError(f"plugin {impl.plugin_name!r} failed in extra_checks: {e}") from e
        for f in found:
            if not {"source_row", "check", "severity"} <= set(f) or f["severity"] not in ("flag", "quarantine"):
                raise PluginError(f"plugin {impl.plugin_name!r} returned a malformed check result: {f}")
            failures.append({"stage": "validate", "column": f.get("column"), "value": f.get("value"),
                             **f, "check": f"plugin:{impl.plugin_name}:{f['check']}"})
    return failures


MAX_CELL_ENTRIES = 10_000     # per plugin hook; beyond this one summary entry is written


def cell_changes(before: pd.DataFrame, after: pd.DataFrame, rule: str) -> list[dict]:
    """One log entry per changed cell (row, column, old, new); added/removed columns are logged too."""
    entries = []
    rows = before[SOURCE_ROW] if SOURCE_ROW in before else pd.Series(range(len(before)), index=before.index)
    for col in [c for c in after.columns if c not in before.columns]:
        entries.append({"stage": "plugin", "rule": rule, "source_row": None, "column": col, "old": None,
                        "new": None, "detail": "column added by plugin"})
    for col in [c for c in before.columns if c not in after.columns]:
        entries.append({"stage": "plugin", "rule": rule, "source_row": None, "column": col, "old": None,
                        "new": None, "detail": "column removed by plugin"})
    total = 0
    for col in [c for c in before.columns if c in after.columns and c != SOURCE_ROW]:
        a, b = before[col], after[col]
        differ = ~((a.isna() & b.isna()) | (a.astype("string") == b.astype("string")).fillna(False))
        for i in a.index[differ.values]:
            total += 1
            if total <= MAX_CELL_ENTRIES:
                entries.append({"stage": "plugin", "rule": rule, "source_row": int(rows[i]), "column": col,
                                "old": _plain(a[i]), "new": _plain(b[i])})
    if total > MAX_CELL_ENTRIES:
        entries.append({"stage": "plugin", "rule": rule, "source_row": None, "column": None, "old": None, "new": None,
                        "detail": f"{total - MAX_CELL_ENTRIES} more changed cell(s) not listed individually"})
    return entries


def _plain(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat(sep=" ")
    return v.item() if hasattr(v, "item") else v


def plugin_info(pm: pluggy.PluginManager | None) -> list[dict]:
    """Which plugin code ran: module, file, SHA-256 of the file, version (for reproducibility)."""
    import hashlib
    from pathlib import Path

    out = []
    for name, module in (pm.list_name_plugin() if pm else []):
        f = getattr(module, "__file__", None)
        out.append({"name": name, "file": f, "version": getattr(module, "__version__", None),
                    "sha256": hashlib.sha256(Path(f).read_bytes()).hexdigest() if f else None,
                    "hooks": sorted(h.name for h in pm.get_hookcallers(module) or [])})
    return out
