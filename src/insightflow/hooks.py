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
        changed = _count_changes(data, out)
        log.append({"stage": "plugin", "rule": f"{name}.{hook}", "source_row": 0, "column": None,
                    "old": None, "new": None, "detail": f"{changed} cell(s) changed"})
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


def _count_changes(a: pd.DataFrame, b: pd.DataFrame) -> int:
    cols = [c for c in a.columns if c in b.columns and c != SOURCE_ROW]
    left, right = a[cols].astype("string"), b[cols].astype("string")
    diff = ~(left.fillna("\x00").values == right.fillna("\x00").values)
    return int(diff.sum()) + len(set(b.columns) ^ set(a.columns))
