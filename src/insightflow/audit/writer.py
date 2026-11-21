"""Step 8: write the outputs and the audit trail of one pipeline run.

data/processed/<ID>/  cleaned_<domain>.csv, quality_report.json, cleaning_log.json, metadata.json
data/quarantine/<ID>/ quarantined_rows.csv (ORIGINAL text + reasons), duplicates_removed.csv
data/raw/<ID>/        an untouched copy of the input file (+ data/raw/_registry.json)
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd

from insightflow.ingestion import SOURCE_ROW

SOURCE_ROW_OUT = "source_row"


def _json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def _csv(path: Path, df: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8", lineterminator="\n")
    tmp.replace(path)
    return path


def to_output_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Typed frame -> stable text output: ISO dates, plain numbers, blanks for missing."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    return out.rename(columns={SOURCE_ROW: SOURCE_ROW_OUT})


def preserve_raw(src: Path, raw_root: Path, dataset_id: str, sha256: str) -> Path:
    """Copy the input into data/raw/<ID>/ once; never overwrite a different file with the same name."""
    target_dir = raw_root / dataset_id
    target = target_dir / src.name
    if src.resolve() == target.resolve():
        return target
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() == sha256:
            return target
        target = target_dir / f"{src.stem}__{sha256[:8]}{src.suffix}"
        if target.exists():
            return target
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target


def write_run(*, data_root: Path, dataset_id: str, domain: str, cleaned: pd.DataFrame,
              quarantine: pd.DataFrame, duplicates: pd.DataFrame, quality_report: dict,
              cleaning_log: list[dict], metadata: dict) -> dict[str, str]:
    processed = data_root / "processed" / dataset_id
    qdir = data_root / "quarantine" / dataset_id
    paths = {
        "cleaned": _csv(processed / f"cleaned_{domain}.csv", to_output_frame(cleaned)),
        "quarantine": _csv(qdir / "quarantined_rows.csv", quarantine.rename(columns={SOURCE_ROW: SOURCE_ROW_OUT})),
        "duplicates": _csv(qdir / "duplicates_removed.csv", duplicates.rename(columns={SOURCE_ROW: SOURCE_ROW_OUT})),
        "quality_report": _json(processed / "quality_report.json", quality_report),
        "cleaning_log": _json(processed / "cleaning_log.json", cleaning_log),
    }
    out = {k: str(v) for k, v in paths.items()}
    out["metadata"] = str(processed / "metadata.json")
    metadata["output_paths"] = out
    _json(processed / "metadata.json", metadata)
    return out
