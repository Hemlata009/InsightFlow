"""Local web API for exploring InsightFlow from the React UI (http://127.0.0.1:8000).

Local only: binds to 127.0.0.1, one pipeline run at a time (low-RAM PC), uploads limited by the
rule book's max_file_mb and stored under data/uploads/ (git-ignored).
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from insightflow import __version__
from insightflow.config import CONFIG_DIR, load_dataset_config
from insightflow.ingestion import IngestionError, read_file
from insightflow.normalization import NotConvertible, parse_dates, parse_number
from insightflow.pipeline.phase1 import DATA_ROOT, ROOT, run_phase1
from insightflow.profiling import profile

WEB_DIST = ROOT / "web" / "dist"
ALLOWED_SUFFIXES = {".csv", ".tsv", ".txt", ".xlsx", ".json", ".jsonl", ".ndjson", ".parquet"}
TABLES = {"cleaned": ("processed", None), "quarantine": ("quarantine", "quarantined_rows.csv"),
          "duplicates": ("quarantine", "duplicates_removed.csv")}
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_run_lock = threading.Lock()


class LabRequest(BaseModel):
    dataset_id: str
    values: list[str]
    ambiguous_dates: str | None = None   # "use_locale" | "quarantine"


def create_app(data_root: Path = DATA_ROOT, config_dir: Path = CONFIG_DIR) -> FastAPI:
    app = FastAPI(title="InsightFlow local API", version=__version__)

    # ------------------------------------------------------------ helpers
    def cfg_or_404(dataset_id: str):
        if not _ID.match(dataset_id) or not (config_dir / "datasets" / f"{dataset_id}.yaml").exists():
            raise HTTPException(404, f"unknown dataset {dataset_id!r}")
        return load_dataset_config(dataset_id, config_dir)

    def resolve_input(dataset_id: str, sample: str | None, upload: UploadFile | None, max_mb: float) -> Path:
        if upload is not None and upload.filename:
            name = Path(upload.filename).name
            if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
                raise HTTPException(400, f"supported files: {sorted(ALLOWED_SUFFIXES)}")
            safe = re.sub(r"[^A-Za-z0-9._\- ]", "_", name)
            target = data_root / "uploads" / uuid.uuid4().hex[:12] / safe
            target.parent.mkdir(parents=True, exist_ok=True)
            limit, size = max_mb * 2**20, 0
            with open(target, "wb") as out:
                while chunk := upload.file.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        out.close()
                        target.unlink(missing_ok=True)
                        raise HTTPException(413, f"file larger than {max_mb} MB")
                    out.write(chunk)
            return target
        if sample:
            if Path(sample).name != sample:
                raise HTTPException(400, "invalid sample name")
            p = data_root / "sample" / dataset_id / sample
            if not p.is_file() or p.suffix.lower() not in ALLOWED_SUFFIXES:
                raise HTTPException(404, f"sample {sample!r} not found for {dataset_id}")
            return p
        raise HTTPException(400, "choose a sample file or upload one")

    def processed(dataset_id: str) -> Path:
        return data_root / "processed" / dataset_id

    # ------------------------------------------------------------ info
    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/datasets")
    def datasets():
        out = []
        for f in sorted((config_dir / "datasets").glob("*.yaml")):
            cfg = load_dataset_config(f.stem, config_dir)
            sdir = data_root / "sample" / f.stem
            samples = sorted(p.name for p in sdir.glob("*") if p.suffix.lower() in ALLOWED_SUFFIXES) \
                if sdir.exists() else []
            out.append({"dataset_id": cfg.dataset_id, "domain": cfg.domain, "locale": cfg.locale_name,
                        "currency": cfg.locale.currency_code, "date_order": cfg.locale.date_order,
                        "description": cfg.description, "samples": samples,
                        "has_run": (processed(f.stem) / "metadata.json").exists()})
        return out

    @app.get("/api/datasets/{dataset_id}/rules")
    def rules(dataset_id: str):
        return cfg_or_404(dataset_id).model_dump(mode="json")

    # ------------------------------------------------------------ actions
    @app.post("/api/profile")
    def run_profile(dataset_id: str = Form(...), sample: str | None = Form(None),
                    file: UploadFile | None = File(None)):
        cfg = cfg_or_404(dataset_id)
        path = resolve_input(dataset_id, sample, file, cfg.policies.max_file_mb)
        try:
            r = read_file(path, known_headers=set(cfg.header_map()))
        except IngestionError as e:
            return {"ok": False, "error": {"code": e.code, "message": e.message}}
        return {"ok": True, "read_warnings": r.warnings, "bad_rows": r.bad_rows[:50],
                "report": json.loads(json.dumps(profile(r.data, cfg, r.metadata), default=str))}

    @app.post("/api/run")
    def run(dataset_id: str = Form(...), sample: str | None = Form(None),
            file: UploadFile | None = File(None)):
        cfg = cfg_or_404(dataset_id)
        path = resolve_input(dataset_id, sample, file, cfg.policies.max_file_mb)
        if not _run_lock.acquire(timeout=1):
            raise HTTPException(409, "a pipeline run is already in progress; try again shortly")
        try:
            return run_phase1(path, dataset_id, data_root=data_root, config_dir=config_dir)
        finally:
            _run_lock.release()

    # ------------------------------------------------------------ results of the latest run
    @app.get("/api/runs/{dataset_id}/latest")
    def latest(dataset_id: str):
        cfg_or_404(dataset_id)
        meta = processed(dataset_id) / "metadata.json"
        if not meta.exists():
            raise HTTPException(404, "no run yet for this dataset")
        out = {"metadata": json.loads(meta.read_text(encoding="utf-8"))}
        qr = processed(dataset_id) / "quality_report.json"
        out["quality_report"] = json.loads(qr.read_text(encoding="utf-8")) if qr.exists() else None
        return out

    @app.get("/api/runs/{dataset_id}/table/{kind}")
    def table(dataset_id: str, kind: str, offset: int = 0, limit: int = 50, search: str = ""):
        cfg = cfg_or_404(dataset_id)
        if kind not in TABLES:
            raise HTTPException(404, f"unknown table {kind!r}")
        sub, name = TABLES[kind]
        p = data_root / sub / dataset_id / (name or f"cleaned_{cfg.domain}.csv")
        if not p.exists():
            raise HTTPException(404, "no run yet for this dataset")
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        if search:
            mask = df.apply(lambda c: c.str.contains(search, case=False, regex=False)).any(axis=1)
            df = df[mask]
        limit = max(1, min(limit, 500))
        page = df.iloc[max(0, offset): offset + limit]
        return {"total": int(len(df)), "offset": offset, "columns": list(df.columns),
                "rows": page.to_dict(orient="records")}

    @app.get("/api/runs/{dataset_id}/log")
    def log(dataset_id: str, offset: int = 0, limit: int = 50, stage: str = "", rule: str = "",
            row: int | None = None):
        cfg_or_404(dataset_id)
        p = processed(dataset_id) / "cleaning_log.json"
        if not p.exists():
            raise HTTPException(404, "no run yet for this dataset")
        entries = json.loads(p.read_text(encoding="utf-8"))
        if stage:
            entries = [e for e in entries if e.get("stage") == stage]
        if rule:
            entries = [e for e in entries if rule.lower() in str(e.get("rule") or e.get("check") or
                                                                 e.get("flag") or e.get("reason") or "").lower()]
        if row is not None:
            entries = [e for e in entries if e.get("source_row") == row]
        limit = max(1, min(limit, 500))
        return {"total": len(entries), "offset": offset, "entries": entries[offset: offset + limit]}

    # ------------------------------------------------------------ edge-case lab
    @app.post("/api/lab/number")
    def lab_number(req: LabRequest):
        cfg = cfg_or_404(req.dataset_id)
        out = []
        for v in req.values[:200]:
            try:
                value, how = parse_number(v, cfg.locale)
                out.append({"input": v, "ok": True, "value": value, "how": how})
            except NotConvertible as e:
                out.append({"input": v, "ok": False, "reason": e.reason, "detail": str(e)})
        return {"locale": cfg.locale_name, "results": out}

    @app.post("/api/lab/date")
    def lab_date(req: LabRequest):
        cfg = cfg_or_404(req.dataset_id)
        if req.ambiguous_dates in ("use_locale", "quarantine"):
            cfg = cfg.model_copy(deep=True)
            cfg.policies.ambiguous_dates = req.ambiguous_dates
        values = req.values[:200]
        dates, rule, reason = parse_dates(pd.Series(values, dtype="string"), cfg)
        out = []
        for i, v in enumerate(values):
            ok = pd.notna(dates.iloc[i])
            out.append({"input": v, "ok": bool(ok),
                        "value": dates.iloc[i].date().isoformat() if ok else None,
                        "how": None if pd.isna(rule.iloc[i]) else str(rule.iloc[i]),
                        "reason": None if pd.isna(reason.iloc[i]) else str(reason.iloc[i])})
        return {"locale": cfg.locale_name, "date_order": cfg.locale.date_order,
                "date_range": [str(cfg.date_range.min), str(cfg.date_range.max)], "results": out}

    # ------------------------------------------------------------ the built React app
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "not found")
            f = WEB_DIST / path
            if path and f.is_file() and WEB_DIST in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app()
