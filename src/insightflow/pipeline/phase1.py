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
from insightflow.cleaning import REASONS, clean
from insightflow.config import CONFIG_DIR, load_dataset_config
from insightflow.ingestion import SOURCE_ROW, FileRegistry, IngestionError, IngestOptions, read_file
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
              "error": None, "output_paths": {}}

    cfg = load_dataset_config(dataset_id, config_dir)
    try:
        raw = read_file(input_path, known_headers=set(cfg.header_map()),
                        options=IngestOptions(max_file_mb=cfg.policies.max_file_mb))
    except IngestionError as e:
        result["error"] = {"code": e.code, "message": e.message}
        return _finish_failed(result, data_root, started)

    meta = raw.metadata
    warnings = list(raw.warnings)
    result["rows_input"] = meta.rows + len(raw.bad_rows)

    # repeated upload + untouched raw copy
    registry = FileRegistry(data_root / "raw" / "_registry.json")
    is_new, entry = registry.register(meta, dataset_id)
    if not is_new:
        warnings.append(f"this exact file was processed before (first seen {entry['first_seen']} "
                        f"as {entry['file_name']}); results are recomputed")
    raw_copy = preserve_raw(input_path, data_root / "raw", dataset_id, meta.sha256)

    before = profile(raw.data, cfg, meta)
    norm = normalize(raw.data, cfg)
    warnings += norm.warnings
    if norm.missing_required:
        result["error"] = {"code": "missing_required_columns",
                           "message": f"required column(s) not found: {norm.missing_required}"}
        result["validation_errors"] = [result["error"]["message"]]
        return _finish_failed(result, data_root, started, meta)

    cleaned = clean(norm, cfg)
    from insightflow.validation import validate      # imported here: pandera is the slowest import
    val = validate(cleaned.data, cfg)
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

    raw_by_row = raw.data.set_index(SOURCE_ROW)
    q_rows = sorted(q_reasons)
    quarantine = raw_by_row.reindex(q_rows).reset_index()          # ORIGINAL text, for a human to fix
    for b in raw.bad_rows:
        quarantine.loc[quarantine[SOURCE_ROW] == b["source_row"], "_raw_values"] = json.dumps(b["values"],
                                                                                              ensure_ascii=False)
    quarantine[REASONS] = [q_reasons[r] for r in q_rows]

    # flags only matter for rows we keep; a quarantined row's extra flags stay in the log only
    kept = set(final[SOURCE_ROW].astype(int))
    effective = [f for f in val.failures if f["severity"] == "quarantine" or f["source_row"] in kept]
    flags = [f for f in cleaned.flags + [f for f in val.failures if f["severity"] == "flag"]
             if f["source_row"] in kept]
    log = norm.changes + norm.issues + cleaned.actions + flags + \
        [f for f in val.failures if f["severity"] == "quarantine"]
    transformations = _count(norm.changes + cleaned.actions, "rule")

    n_in = result["rows_input"]
    share = len(quarantine) / n_in if n_in else 0.0
    status = ("needs_review" if share > cfg.policies.max_quarantine_share else
              "completed_with_warnings" if (len(quarantine) or flags or warnings) else "completed")
    result.update(
        status=status, rows_output=len(final), rows_quarantined=len(quarantine),
        rows_duplicates_removed=len(cleaned.duplicates), rows_flagged=len({f["source_row"] for f in flags}),
        transformations_applied=transformations,
        validation_errors=[f"{k}: {v['rows']} row(s) [{v['severity']}]" for k, v in _summary(effective).items()],
        warnings=warnings,
    )
    if len(final) + len(quarantine) + len(cleaned.duplicates) != n_in:     # every row must be accounted for
        raise RuntimeError("row accounting mismatch: rows were lost or double-counted")

    quality = {
        "dataset_id": dataset_id, "run_id": run_id,
        "before": before,
        "after": {"rows": len(final),
                  "missing_by_column": {c: int(final[c].isna().sum()) for c in final.columns if c != SOURCE_ROW},
                  "quarantine_reasons": _count([{"r": r.split(":")[0]} for rs in q_reasons.values()
                                                for r in rs.split("; ")], "r"),
                  "flags": _count(flags, "flag", fallback="check")},
        "validation": {"checks_run": val.checks_run, "summary": _summary(effective)},
        "quarantine_share": round(share, 4),
    }
    metadata = _metadata(result, cfg, meta, started, str(raw_copy), config_dir)
    result["output_paths"] = write_run(
        data_root=data_root, dataset_id=dataset_id, domain=cfg.domain, cleaned=final,
        quarantine=quarantine, duplicates=cleaned.duplicates, quality_report=quality,
        cleaning_log=log, metadata=metadata)
    return result


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
    for w in result["warnings"]:
        lines.append(f"  warning: {w}")
    for k, p in result["output_paths"].items():
        lines.append(f"  output : {k:<14} {p}")
    return "\n".join(lines)
