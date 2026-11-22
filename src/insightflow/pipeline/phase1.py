"""Step 9: the complete Phase 1 pipeline, one call from raw file to audited clean data.

    result = run_phase1("data/sample/SALES_002/sales_messy.xlsx", "SALES_002")
    result["status"]   # completed | completed_with_warnings | needs_review | failed

Stages: ingest -> profile -> normalize -> clean -> validate -> write outputs + audit.
The result dict has the same shape for every input, so MCP tools / LangGraph can read it later.
"""

from __future__ import annotations

import hashlib
import json
import platform
import uuid
from datetime import datetime
from importlib import metadata as pkg_meta
from pathlib import Path

from insightflow import __version__
from insightflow.audit import preserve_raw, write_run
import pandas as pd

from insightflow.cleaning import REASONS, clean
from insightflow.cleaning.repair import add_original_text, candidate_rows, repair_rows
from insightflow.config import CONFIG_DIR, load_dataset_config
from insightflow.audit.log import AuditLog, summarize
from insightflow.hooks import PluginError, load_plugins, plugin_info, run_checks, run_transform
from insightflow.ingestion import (SOURCE_ROW, FileMetadata, FileRegistry, IngestionError, IngestOptions,
                                   file_sha256, read_file)
from insightflow.ingestion.reader import SUPPORTED
from insightflow.pipeline.chunked import STREAMABLE, run_chunked
from insightflow.normalization.partial_dates import resolve_partial_dates
from insightflow.pipeline.messages import is_note, split_messages
from insightflow.normalization import normalize
from insightflow.profiling import profile

ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "data"


def run_phase1(input_path: str | Path, dataset_id: str, *, data_root: Path = DATA_ROOT,
               config_dir: Path = CONFIG_DIR) -> dict:
    input_path = Path(input_path)
    started = datetime.now()
    run_id = f"{dataset_id}-{started:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    result = {"dataset_id": dataset_id, "run_id": run_id, "status": "failed",
              "source_file": str(input_path), "source_format": input_path.suffix.lstrip(".").lower(),
              "rows_input": 0, "rows_output": 0, "rows_quarantined": 0, "rows_duplicates_removed": 0,
              "rows_flagged": 0, "transformations_applied": {}, "validation_errors": [], "warnings": [],
              "notes": [], "schema_changes": {}, "plugins": [], "processing_mode": None,
              "error": None, "output_paths": {}}

    cfg = load_dataset_config(dataset_id, config_dir)
    result["plugins"] = list(cfg.plugins)
    try:
        return _run(result, input_path, dataset_id, cfg, data_root, config_dir, started)
    except PluginError as e:
        result["error"] = {"code": "plugin_error", "message": str(e)}
        return _finish_failed(result, data_root, started)


def _run(result, input_path, dataset_id, cfg, data_root, config_dir, started) -> dict:
    pm = load_plugins(cfg.plugins) if cfg.plugins else None
    plugin_log: list[dict] = []
    mode = cfg.policies.large_files
    fmt = SUPPORTED.get(input_path.suffix.lower())
    if mode == "always" and fmt in STREAMABLE:
        return _run_chunked(result, input_path, cfg, data_root, config_dir, started, fmt, pm=pm)
    try:
        raw = read_file(input_path, known_headers=set(cfg.header_map()),
                        options=IngestOptions(max_file_mb=cfg.policies.max_file_mb,
                                              header_rows=cfg.policies.header_rows))
    except IngestionError as e:
        if e.code in ("too_large", "insufficient_memory") and mode == "auto" and fmt in STREAMABLE:
            return _run_chunked(result, input_path, cfg, data_root, config_dir, started, fmt, reason=e.message,
                                pm=pm)
        result["error"] = {"code": e.code, "message": e.message}
        return _finish_failed(result, data_root, started)
    result["processing_mode"] = "in_memory"

    meta = raw.metadata
    warnings = list(raw.warnings)
    original_text = raw.data                                   # kept for the quarantine file
    if pm:
        raw.data = run_transform(pm, "after_ingest", raw.data, cfg, plugin_log)
    result["rows_input"] = meta.rows + len(raw.bad_rows)

    # repeated upload + untouched raw copy
    registry = FileRegistry(data_root / "raw" / "_registry.json")
    is_new, entry = registry.register(meta, dataset_id)
    if not is_new:
        warnings.append(f"this exact file was processed before (first seen {entry['first_seen']} "
                        f"as {entry['file_name']}); results are recomputed")
    raw_copy = preserve_raw(input_path, data_root / "raw", dataset_id, meta.sha256)
    changes = _schema_changes(data_root / "processed" / dataset_id / "metadata.json", meta.columns, cfg)
    if changes:
        result["schema_changes"] = changes       # always recorded
        warnings += drift_messages(changes, cfg)

    before = profile(raw.data, cfg, meta)
    norm = normalize(raw.data, cfg)
    warnings += norm.warnings
    if pm:
        norm.data = run_transform(pm, "after_normalize", norm.data, cfg, plugin_log)
    resolve_partial_dates(norm, cfg, pm)
    if norm.missing_required:
        result["error"] = {"code": "missing_required_columns",
                           "message": f"required column(s) not found: {norm.missing_required}"}
        result["validation_errors"] = [result["error"]["message"]]
        return _finish_failed(result, data_root, started, meta)

    cleaned = clean(norm, cfg)
    if pm:
        cleaned.data = run_transform(pm, "after_clean", cleaned.data, cfg, plugin_log)
    from insightflow.validation import validate      # imported here: pandera is the slowest import
    val = validate(cleaned.data, cfg)
    if pm:
        val.failures += run_checks(pm, cleaned.data, cfg)
    if val.structural_errors:
        result["error"] = {"code": "schema_error", "message": "; ".join(val.structural_errors)}
        result["validation_errors"] = val.structural_errors
        return _finish_failed(result, data_root, started, meta)

    # rows that fail quarantine-level checks leave the clean set, with reasons
    vq: dict[int, list[str]] = {}
    for f in val.failures:
        if f["severity"] == "quarantine":
            vq.setdefault(f["source_row"], []).append(f"{f['check']}:{f['column']}")
    final = cleaned.data[~cleaned.data[SOURCE_ROW].isin(vq)].reset_index(drop=True)
    q_reasons = dict(zip(cleaned.quarantine[SOURCE_ROW].astype(int), cleaned.quarantine[REASONS]))
    for r, rs in vq.items():
        q_reasons[r] = "; ".join(filter(None, [q_reasons.get(r), *rs]))
    for b in raw.bad_rows:
        q_reasons[b["source_row"]] = f"unreadable_row:{b['reason']}"

    # proven repairs from the formula (exactly one bad value, everything else consistent): kept + flagged
    cand = candidate_rows(norm.data, cleaned, vq)
    repaired, repair_log, repair_flags = repair_rows(cand, q_reasons, cfg)
    rows_fixed = set(repaired[SOURCE_ROW].astype(int)) if len(repaired) else set()
    if rows_fixed:
        final = pd.concat([final, repaired], ignore_index=True).sort_values(SOURCE_ROW).reset_index(drop=True)
        for r in rows_fixed:
            q_reasons.pop(r, None)
        add_original_text(repair_log, original_text, norm.header_changes)
        # repaired rows join the repeat / key checks too (chunked mode does this in DuckDB)
        value_cols = [c for c in final.columns if c != SOURCE_ROW]
        dup = final.duplicated(subset=value_cols, keep="first") & final[SOURCE_ROW].isin(rows_fixed)
        if dup.any():
            first = final.groupby(value_cols, dropna=False, sort=False)[SOURCE_ROW].transform("first")
            extra = pd.DataFrame({SOURCE_ROW: final.loc[dup, SOURCE_ROW], "duplicate_of": first[dup]})
            cleaned.duplicates = pd.concat([cleaned.duplicates, extra], ignore_index=True)
            final = final.loc[~dup].reset_index(drop=True)
        key = [k for k in cfg.duplicates.key if k in final]
        if key and cfg.duplicates.key_conflict == "flag":
            conflict = final.duplicated(subset=key, keep=False) & final[key].notna().all(axis=1)
            groups = final.loc[conflict].groupby(key, dropna=False)[SOURCE_ROW].apply(set)
            already = {f["source_row"] for f in cleaned.flags if f.get("flag") == "key_conflict"}
            for rows in groups:
                if rows & rows_fixed:
                    repair_flags += [{"stage": "clean", "flag": "key_conflict", "source_row": int(r),
                                      "column": "+".join(key)} for r in rows - already]

    raw_by_row = original_text.set_index(SOURCE_ROW)
    q_rows = sorted(q_reasons)
    quarantine = raw_by_row.reindex(q_rows).reset_index()          # ORIGINAL text, for a human to fix
    for b in raw.bad_rows:
        quarantine.loc[quarantine[SOURCE_ROW] == b["source_row"], "_raw_values"] = json.dumps(b["values"],
                                                                                              ensure_ascii=False)
    quarantine[REASONS] = [q_reasons[r] for r in q_rows]

    # flags only matter for rows we keep; a quarantined row's extra flags stay in the log only
    currency_info = {}
    if cfg.currency.reporting_currency:
        from insightflow.normalization.currency import add_reporting_columns
        final, currency_info = add_reporting_columns(final, cfg)
        if currency_info["rows_without_rate"]:
            warnings.append(f"{currency_info['rows_without_rate']} row(s) have no {currency_info['reporting_currency']} "
                            f"rate for their date; their {currency_info['reporting_currency']} columns are blank")
    kept = set(final[SOURCE_ROW].astype(int))
    effective = [f for f in val.failures if (f["severity"] == "quarantine" or f["source_row"] in kept)
                 and f["source_row"] not in rows_fixed]
    flags = [f for f in cleaned.flags + repair_flags +
             [f for f in val.failures if f["severity"] == "flag" and f["source_row"] not in rows_fixed]
             if f["source_row"] in kept]          # (a repaired row's checks from BEFORE the repair don't count)
    log = plugin_log + norm.changes + norm.issues + cleaned.actions + repair_log + flags + \
        [f for f in val.failures if f["severity"] == "quarantine"]
    transformations = _count(norm.changes + cleaned.actions + repair_log, "rule")

    n_in = result["rows_input"]
    share = len(quarantine) / n_in if n_in else 0.0
    notes, warnings = split_messages(warnings)          # information never changes the status
    status = ("needs_review" if share > cfg.policies.max_quarantine_share else
              "completed_with_warnings" if (len(quarantine) or flags or warnings) else "completed")
    result.update(
        status=status, rows_output=len(final), rows_quarantined=len(quarantine),
        rows_duplicates_removed=len(cleaned.duplicates), rows_flagged=len({f["source_row"] for f in flags}),
        transformations_applied=transformations,
        validation_errors=[f"{k}: {v['rows']} row(s) [{v['severity']}]" for k, v in _summary(effective).items()],
        warnings=warnings, notes=notes,
    )
    if len(final) + len(quarantine) + len(cleaned.duplicates) != n_in:     # every row must be accounted for
        raise RuntimeError("row accounting mismatch: rows were lost or double-counted")

    quality = {
        "dataset_id": dataset_id, "run_id": result["run_id"],
        "before": before,
        "after": {"rows": len(final),
                  "missing_by_column": {c: int(final[c].isna().sum()) for c in final.columns if c != SOURCE_ROW},
                  "quarantine_reasons": _count([{"r": r.split(":")[0]} for rs in q_reasons.values()
                                                for r in rs.split("; ")], "r"),
                  "flags": _count(flags, "flag", fallback="check")},
        "validation": {"checks_run": val.checks_run, "summary": _summary(effective)},
        "quarantine_share": round(share, 4),
        "currency": currency_info or None,
    }
    log = AuditLog(result["run_id"]).standardize(log)
    quality["audit"] = summarize(log)
    metadata = _metadata(result, cfg, meta, started, str(raw_copy), config_dir)
    metadata["plugins"] = plugin_info(pm)
    result["output_paths"] = write_run(
        data_root=data_root, dataset_id=dataset_id, domain=cfg.domain, cleaned=final,
        quarantine=quarantine, duplicates=cleaned.duplicates, quality_report=quality,
        cleaning_log=log, metadata=metadata,
        time_columns=[c for c, s in cfg.columns.items() if s.type == "datetime"])
    return result


def _run_chunked(result, input_path, cfg, data_root, config_dir, started, fmt, reason: str = "", pm=None) -> dict:
    """Large files: stream in pieces; see pipeline/chunked.py."""
    warnings = [f"switched to chunked mode: {reason}"] if reason else []
    if pm is not None:
        warnings.append(f"chunked mode: plugins {cfg.plugins} run piece by piece (each call sees one piece)")
    prev_meta = data_root / "processed" / cfg.dataset_id / "metadata.json"
    prev_columns_meta = prev_meta.read_text(encoding="utf-8") if prev_meta.exists() else None

    def finish(res, cfg_used, meta, paths):
        sha = file_sha256(input_path)
        if meta is None:                                   # parquet: no text sample was read
            meta = FileMetadata(file_name=input_path.name, path=str(input_path), format=fmt,
                                size_bytes=input_path.stat().st_size, sha256=sha)
        meta.sha256, meta.size_bytes, meta.rows = sha, input_path.stat().st_size, res["rows_input"]
        meta.path, meta.file_name, meta.format = str(input_path), input_path.name, fmt
        is_new, entry = FileRegistry(data_root / "raw" / "_registry.json").register(meta, cfg.dataset_id)
        if not is_new:
            res["notes"].append(f"this exact file was processed before (first seen {entry['first_seen']})")
        raw_copy = preserve_raw(input_path, data_root / "raw", cfg.dataset_id, sha)
        if prev_columns_meta:
            tmp = data_root / "processed" / cfg.dataset_id / ".prev_metadata.json"
            tmp.write_text(prev_columns_meta, encoding="utf-8")
            changes = _schema_changes(tmp, meta.columns, cfg)
            tmp.unlink()
            if changes:
                res["schema_changes"] = changes
                for m in drift_messages(changes, cfg):
                    if is_note(m):
                        res["notes"].append(m)
                    else:
                        res["warnings"].append(m)
                        if res["status"] == "completed":
                            res["status"] = "completed_with_warnings"
        metadata = _metadata(res, cfg, meta, started, str(raw_copy), config_dir)
        metadata["plugins"] = plugin_info(pm)
        metadata["output_paths"] = {**paths, "metadata": str(data_root / "processed" / cfg.dataset_id / "metadata.json")}
        res["output_paths"] = metadata["output_paths"]
        out = data_root / "processed" / cfg.dataset_id / "metadata.json"
        out.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return res

    try:
        return run_chunked(result, input_path, cfg, data_root, warnings, fmt, started, finish, pm=pm)
    except IngestionError as e:
        result["error"] = {"code": e.code, "message": e.message}
        result["processing_mode"] = "chunked"
        return _finish_failed(result, data_root, started)


def drift_messages(changes: dict, cfg) -> list[str]:
    """Rule-book columns added/removed since the last run -> a warning. Unknown extra columns -> a note."""
    out = []
    for kind in ("added", "removed"):
        cols = changes.get(kind, [])
        known = [c for c in cols if c in cfg.columns]
        extra = [c for c in cols if c not in cfg.columns]
        if known:
            out.append(f"rule-book columns {kind} since the last run: {known}")
        if extra:
            out.append(f"extra column(s) not in the rule book {kind} since the last run: {extra}")
    return out


def _schema_changes(prev_meta: Path, columns: list[str], cfg) -> dict:
    """Compare this file's columns (by canonical name where known) with the previous run's file."""
    if not prev_meta.exists():
        return {}
    try:
        prev = json.loads(prev_meta.read_text(encoding="utf-8")).get("input") or {}
    except (json.JSONDecodeError, OSError):
        return {}
    before, now = prev.get("columns") or [], columns
    if not before:
        return {}
    canon = lambda cols: {cfg.canonical_name(c) or c: c for c in cols}   # noqa: E731
    b, n = canon(before), canon(now)
    out = {}
    added, removed = sorted(set(n) - set(b)), sorted(set(b) - set(n))
    renamed = sorted(f"{b[k]!r} -> {n[k]!r}" for k in set(b) & set(n) if b[k] != n[k])
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if renamed:
        out["header_spelling_changed"] = renamed
    if list(b) != list(n) and not added and not removed:
        out["order_changed"] = True
    return out


def _summary(failures) -> dict:
    out: dict[str, dict] = {}
    for f in failures:
        s = out.setdefault(f["check"], {"severity": f["severity"], "rows": 0})
        s["rows"] += 1
    return out


def _count(items, key, fallback=None):
    out: dict[str, int] = {}
    for i in items:
        k = i.get(key) or (i.get(fallback) if fallback else None) or "other"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def _config_fingerprint(config_dir: Path, dataset_id: str, domain: str) -> str:
    h = hashlib.sha256()
    for rel in ["default.yaml", "locales.yaml", f"domains/{domain}.yaml", f"datasets/{dataset_id}.yaml"]:
        h.update((config_dir / rel).read_bytes())
    return h.hexdigest()


def _versions() -> dict:
    out = {"insightflow": __version__, "python": platform.python_version()}
    for p in ("pandas", "numpy", "pandera", "pydantic", "openpyxl"):
        try:
            out[p] = pkg_meta.version(p)
        except pkg_meta.PackageNotFoundError:
            pass
    return out


def _metadata(result, cfg, meta, started, raw_copy, config_dir) -> dict:
    return {"run_id": result["run_id"], "dataset_id": result["dataset_id"], "domain": cfg.domain,
            "locale": cfg.locale_name, "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "input": meta.to_dict() if meta else None, "raw_copy": raw_copy,
            "config_sha256": _config_fingerprint(config_dir, cfg.dataset_id, cfg.domain),
            "versions": _versions(), "result": {k: v for k, v in result.items() if k != "output_paths"}}


def _finish_failed(result, data_root, started, meta=None) -> dict:
    """A failed run still leaves a metadata.json explaining why."""
    out = data_root / "processed" / result["dataset_id"] / "metadata.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"run_id": result["run_id"], "started_at": started.isoformat(timespec="seconds"),
               "finished_at": datetime.now().isoformat(timespec="seconds"),
               "input": meta.to_dict() if meta else None, "result": result}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    result["output_paths"] = {"metadata": str(out)}
    return result


def describe(result: dict) -> str:
    lines = [f"InsightFlow Phase 1 | {result['dataset_id']} | status: {result['status'].upper()}"]
    if result.get("error"):
        lines.append(f"  error: [{result['error']['code']}] {result['error']['message']}")
    lines += [f"  rows in            : {result['rows_input']}",
              f"  rows clean (out)   : {result['rows_output']}",
              f"  rows quarantined   : {result['rows_quarantined']}",
              f"  duplicates removed : {result['rows_duplicates_removed']}",
              f"  rows flagged       : {result['rows_flagged']}"]
    if result["transformations_applied"]:
        lines.append("  changes: " + ", ".join(f"{k}={v}" for k, v in result["transformations_applied"].items()))
    for v in result["validation_errors"]:
        lines.append(f"  check  : {v}")
    for n in result.get("notes", []):
        lines.append(f"  note   : {n}")
    for w in result["warnings"]:
        lines.append(f"  warning: {w}")
    for k, p in result["output_paths"].items():
        lines.append(f"  output : {k:<14} {p}")
    return "\n".join(lines)
