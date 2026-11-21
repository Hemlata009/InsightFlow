"""Chunked mode for files too big for the free RAM.

Pieces of `chunk_rows` rows are streamed (csv module / pyarrow batches / JSON Lines), each piece goes
through normalize -> clean -> validate exactly like the in-memory pipeline, and the kept rows are
staged in DuckDB (github.com/duckdb/duckdb, MIT) on disk with a memory cap. DuckDB then finds duplicates
and key conflicts ACROSS all pieces and writes the final output, so RAM use stays flat.

Not available in chunked mode (needs the whole table): fill_from_group and impute policies. Those
columns fall back to keep+flag (or quarantine if not nullable), with a warning.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from insightflow.audit.log import AuditLog
from insightflow.audit.writer import SOURCE_ROW_OUT, _json, to_output_frame
from insightflow.cleaning import REASONS, clean
from insightflow.ingestion import SOURCE_ROW, IngestionError, IngestOptions, read_file
from insightflow.normalization import normalize
from insightflow.profiling import profile

STREAMABLE = {"csv", "jsonl", "parquet"}
SAMPLE_BYTES = 256 * 1024


class ChunkedRun:
    def __init__(self, path: Path, cfg, fmt: str, warnings: list[str]):
        self.path, self.cfg, self.fmt, self.warnings = path, cfg, fmt, warnings
        self.meta = None
        self.columns: list[str] = []

    # ------------------------------------------------------------------ reading in pieces
    def sniff(self, known_headers):
        """Detect encoding/delimiter/header from the first part of the file using the normal reader."""
        if self.fmt == "parquet":
            import pyarrow.parquet as pq
            self.columns = [str(c) for c in pq.ParquetFile(self.path).schema_arrow.names]
            self.header_row = 0
            return
        with open(self.path, "rb") as f:
            head = f.read(SAMPLE_BYTES)
        cut = head.rfind(b"\n")
        sample = head[: cut + 1] if cut > 0 else head
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / f"sample{self.path.suffix}"
            p.write_bytes(sample)
            r = read_file(p, known_headers=known_headers, options=IngestOptions(check_memory=False))
        self.meta, self.columns, self.header_row = r.metadata, r.metadata.columns, r.metadata.header_row
        if self.fmt == "jsonl":
            self.columns = self._jsonl_keys()

    def _jsonl_keys(self) -> list[str]:
        keys: dict[str, None] = {}
        with open(self.path, encoding="utf-8-sig") as f:
            for line in f:
                if line.strip():
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        for k in pd.json_normalize(obj, sep=".").columns:
                            keys.setdefault(str(k), None)
        return list(keys)

    def chunks(self, size: int):
        """Yield (DataFrame of text with SOURCE_ROW, bad_rows) per piece."""
        if self.fmt == "csv":
            yield from self._csv_chunks(size)
        elif self.fmt == "jsonl":
            yield from self._jsonl_chunks(size)
        else:
            yield from self._parquet_chunks(size)

    def _frame(self, rows):
        df = pd.DataFrame([r for _, r in rows], columns=self.columns, dtype="string")
        df.insert(0, SOURCE_ROW, [n for n, _ in rows])
        return df

    def _csv_chunks(self, size):
        width = len(self.columns)
        with open(self.path, encoding=self.meta.encoding, newline="") as f:
            reader = csv.reader(f, delimiter=self.meta.delimiter)
            rows, bad = [], []
            for record in reader:
                line = reader.line_num
                if line <= self.header_row or not any(c.strip() for c in record):
                    continue
                if len(record) > width and not any(c.strip() for c in record[width:]):
                    record = record[:width]
                if len(record) != width:
                    bad.append({"source_row": line, "reason": f"{len(record)} fields, expected {width}",
                                "values": record})
                    continue
                rows.append((line, record))
                if len(rows) >= size:
                    yield self._frame(rows), bad
                    rows, bad = [], []
            if rows or bad:
                yield self._frame(rows), bad

    def _jsonl_chunks(self, size):
        from insightflow.ingestion.reader import _json_text
        with open(self.path, encoding="utf-8-sig") as f:
            rows, bad = [], []
            for n, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    obj = None
                if not isinstance(obj, dict):
                    bad.append({"source_row": n, "reason": "not a JSON object", "values": [line[:200]]})
                    continue
                flat = pd.json_normalize(obj, sep=".").iloc[0].to_dict()
                rows.append((n, [_json_text(flat.get(c)) for c in self.columns]))
                if len(rows) >= size:
                    yield self._frame(rows), bad
                    rows, bad = [], []
            if rows or bad:
                yield self._frame(rows), bad

    def _parquet_chunks(self, size):
        import pyarrow.parquet as pq
        from insightflow.ingestion.reader import _json_text
        n = 0
        for batch in pq.ParquetFile(self.path).iter_batches(batch_size=size):
            frame = batch.to_pandas()
            rows = []
            for rec in frame.itertuples(index=False):
                n += 1
                rows.append((n, [_json_text(v) for v in rec]))
            yield self._frame(rows), []


def run_chunked(result: dict, input_path: Path, cfg, data_root: Path, warnings: list[str], fmt: str,
                started, finish) -> dict:
    """Chunked counterpart of the in-memory pipeline. `finish(result, quality, log_path, ...)` writes metadata."""
    import duckdb

    from insightflow.validation import validate

    p = cfg.policies
    size_mb = input_path.stat().st_size / 2**20
    if fmt not in STREAMABLE:
        raise IngestionError("too_large", f"{input_path.name} is too big to load and {fmt} files can't be read in "
                                          "pieces; save it as CSV or Parquet")
    if size_mb > p.max_chunked_file_mb:
        raise IngestionError("too_large", f"{input_path.name} is {size_mb:.0f} MB > max_chunked_file_mb "
                                          f"{p.max_chunked_file_mb:.0f} MB")
    cfg = _without_whole_table_policies(cfg, warnings)
    warnings.append(f"large file ({size_mb:.0f} MB): processed in pieces of {p.chunk_rows:,} rows; "
                    "duplicates found across all pieces with DuckDB")

    run = ChunkedRun(input_path, cfg, fmt, warnings)
    run.sniff(set(cfg.header_map()))
    processed = data_root / "processed" / cfg.dataset_id
    qdir = data_root / "quarantine" / cfg.dataset_id
    processed.mkdir(parents=True, exist_ok=True)
    qdir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="if_chunks_", dir=data_root))
    con = duckdb.connect(str(work / "stage.duckdb"))
    con.execute(f"SET memory_limit='{p.duckdb_memory_mb}MB'; SET threads=2; "
                f"SET temp_directory='{(work / 'spill').as_posix()}'; SET preserve_insertion_order=true")

    log_path = processed / "cleaning_log.json"
    q_path = qdir / "quarantined_rows.csv"
    counts = {"rows_input": 0, "quarantined": 0, "flags": set(), "transformations": {}, "checks": {}}
    before = None
    q_header_written = False
    try:
        with open(log_path, "w", encoding="utf-8") as log, open(q_path, "w", encoding="utf-8-sig", newline="") as qf:
            log.write("[\n")
            first_log = [True]
            audit = AuditLog(result["run_id"])
            kinds: dict[str, int] = {}

            def emit(entries):
                for e in audit.standardize(entries):
                    kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
                    log.write(("" if first_log[0] else ",\n") + json.dumps(e, ensure_ascii=False, default=str))
                    first_log[0] = False

            spellings = _whole_file_spellings(run, cfg, p.chunk_rows)
            group_values = _whole_file_group_values(run, cfg, p.chunk_rows, spellings)
            for i, (raw, bad) in enumerate(run.chunks(p.chunk_rows)):
                counts["rows_input"] += len(raw) + len(bad)
                if before is None and len(raw):
                    before = profile(raw, cfg, run.meta)
                    before["sampled"] = f"first piece only ({len(raw):,} rows)"
                norm = normalize(raw, cfg, spellings=spellings) if len(raw) else None
                if norm is not None and norm.missing_required:
                    raise IngestionError("missing_required_columns",
                                         f"required column(s) not found: {norm.missing_required}")
                cleaned = clean(norm, cfg, dedupe=False, group_values=group_values) if norm is not None else None
                val = validate(cleaned.data, cfg) if cleaned is not None else None
                if val is not None and val.structural_errors:
                    raise IngestionError("schema_error", "; ".join(val.structural_errors))

                reasons = {}
                if cleaned is not None:
                    reasons.update(dict(zip(cleaned.quarantine[SOURCE_ROW].astype(int), cleaned.quarantine[REASONS])))
                    for f in val.failures:
                        if f["severity"] == "quarantine":
                            r = f["source_row"]
                            reasons[r] = "; ".join(filter(None, [reasons.get(r), f"{f['check']}:{f['column']}"]))
                for b in bad:
                    reasons[b["source_row"]] = f"unreadable_row:{b['reason']}"
                kept = cleaned.data[~cleaned.data[SOURCE_ROW].isin(reasons)] if cleaned is not None else None

                # quarantine: ORIGINAL text + reasons, appended piece by piece
                q = raw.set_index(SOURCE_ROW).reindex(sorted(reasons)).reset_index()
                for b in bad:
                    q.loc[q[SOURCE_ROW] == b["source_row"], "_raw_values"] = json.dumps(b["values"], ensure_ascii=False)
                if "_raw_values" not in q:
                    q["_raw_values"] = pd.NA
                q[REASONS] = [reasons[r] for r in q[SOURCE_ROW]]
                q = q.rename(columns={SOURCE_ROW: SOURCE_ROW_OUT})
                q.to_csv(qf, index=False, header=not q_header_written, lineterminator="\n")
                q_header_written = True
                counts["quarantined"] += len(q)

                if kept is not None and len(kept):
                    kept_set = set(kept[SOURCE_ROW].astype(int))
                    flags = [f for f in (cleaned.flags + [f for f in val.failures if f["severity"] == "flag"])
                             if f["source_row"] in kept_set]
                    counts["flags"] |= {f["source_row"] for f in flags}
                    for f in val.failures:
                        if f["severity"] == "quarantine" or f["source_row"] in kept_set:
                            s = counts["checks"].setdefault(f["check"], {"severity": f["severity"], "rows": 0})
                            s["rows"] += 1
                    if cfg.currency.reporting_currency:
                        from insightflow.normalization.currency import add_reporting_columns
                        kept, _ = add_reporting_columns(kept, cfg)
                    out = to_output_frame(kept, [c for c, s in cfg.columns.items() if s.type == "datetime"])
                    if i == 0 or not _table_exists(con, "stage"):
                        con.execute("CREATE TABLE stage AS SELECT * FROM out")
                    else:
                        con.execute("INSERT INTO stage SELECT * FROM out")
                    emit(flags)
                if norm is not None:
                    emit(norm.changes + norm.issues + cleaned.actions +
                         [f for f in val.failures if f["severity"] == "quarantine"])
                    for c in norm.changes + cleaned.actions:
                        counts["transformations"][c["rule"]] = counts["transformations"].get(c["rule"], 0) + 1

            # ---------------- across all pieces, in DuckDB
            dup_rows, conflict_rows, kept_rows = 0, 0, 0
            if _table_exists(con, "stage"):
                cols = [r[0] for r in con.execute("DESCRIBE stage").fetchall()]
                values = ", ".join(_q(c) for c in cols if c != SOURCE_ROW_OUT)
                con.execute(f"""CREATE TABLE ranked AS SELECT *,
                    row_number() OVER (PARTITION BY {values} ORDER BY {_q(SOURCE_ROW_OUT)}) AS _rn,
                    min({_q(SOURCE_ROW_OUT)}) OVER (PARTITION BY {values}) AS _first FROM stage""")
                dup_path = qdir / "duplicates_removed.csv"
                _copy_with_bom(con, f"SELECT {_q(SOURCE_ROW_OUT)}, _first AS duplicate_of FROM ranked WHERE _rn > 1 "
                                    f"ORDER BY {_q(SOURCE_ROW_OUT)}", dup_path, work)
                dup_rows = con.execute("SELECT count(*) FROM ranked WHERE _rn > 1").fetchone()[0]
                key = [k for k in cfg.duplicates.key if k in cols]
                if key:
                    kq = ", ".join(_q(k) for k in key)
                    conflicts = con.execute(f"""SELECT {_q(SOURCE_ROW_OUT)} FROM (
                        SELECT {_q(SOURCE_ROW_OUT)}, count(*) OVER (PARTITION BY {kq}) AS n FROM ranked
                        WHERE _rn = 1 AND {' AND '.join(f'{_q(k)} IS NOT NULL' for k in key)}) WHERE n > 1""").fetchall()
                    conflict_rows = len(conflicts)
                    emit([{"stage": "clean", "flag": "key_conflict", "source_row": int(r[0]), "column": "+".join(key)}
                          for r in conflicts])
                    counts["flags"] |= {int(r[0]) for r in conflicts}
                emit([{"stage": "clean", "rule": "duplicate_removed", "source_row": int(r[0]), "column": None,
                       "old": None, "new": None, "detail": f"same as row {int(r[1])}"}
                      for r in con.execute("SELECT * FROM (SELECT " + _q(SOURCE_ROW_OUT) +
                                           ", _first FROM ranked WHERE _rn > 1)").fetchall()])
                if dup_rows:
                    counts["transformations"]["duplicate_removed"] = dup_rows
                cleaned_path = processed / f"cleaned_{cfg.domain}.csv"
                out_cols = ", ".join(_q(c) for c in cols)
                _copy_with_bom(con, f"SELECT {out_cols} FROM ranked WHERE _rn = 1 ORDER BY {_q(SOURCE_ROW_OUT)}",
                               cleaned_path, work)
                kept_rows = con.execute("SELECT count(*) FROM ranked WHERE _rn = 1").fetchone()[0]
                missing = {c: con.execute(f"SELECT count(*) FROM ranked WHERE _rn = 1 AND {_q(c)} IS NULL").fetchone()[0]
                           for c in cols if c != SOURCE_ROW_OUT}
            else:
                cleaned_path = processed / f"cleaned_{cfg.domain}.csv"
                cleaned_path.write_text("﻿" + ",".join([SOURCE_ROW_OUT, *cfg.columns]) + "\n", encoding="utf-8")
                (qdir / "duplicates_removed.csv").write_text("﻿source_row,duplicate_of\n", encoding="utf-8")
                missing = {}
            log.write("\n]\n")
    finally:
        con.close()
        shutil.rmtree(work, ignore_errors=True)

    n_in = counts["rows_input"]
    if kept_rows + counts["quarantined"] + dup_rows != n_in:
        raise RuntimeError("row accounting mismatch in chunked mode")
    share = counts["quarantined"] / n_in if n_in else 0.0
    flags_n = len(counts["flags"])
    from insightflow.pipeline.messages import split_messages
    notes, warnings = split_messages(warnings)
    status = ("needs_review" if share > p.max_quarantine_share else
              "completed_with_warnings" if (counts["quarantined"] or flags_n or warnings) else "completed")
    result.update(status=status, rows_input=n_in, rows_output=kept_rows, rows_quarantined=counts["quarantined"],
                  rows_duplicates_removed=dup_rows, rows_flagged=flags_n,
                  transformations_applied=dict(sorted(counts["transformations"].items())),
                  validation_errors=[f"{k}: {v['rows']} row(s) [{v['severity']}]" for k, v in counts["checks"].items()],
                  warnings=warnings, notes=notes, processing_mode="chunked")
    quality = {"dataset_id": cfg.dataset_id, "run_id": result["run_id"], "before": before,
               "after": {"rows": kept_rows, "missing_by_column": missing, "key_conflict_rows": conflict_rows},
               "validation": {"summary": counts["checks"]}, "quarantine_share": round(share, 4),
               "audit": {"entries": sum(kinds.values()), "by_kind": dict(sorted(kinds.items()))}}
    paths = {"cleaned": str(cleaned_path), "quarantine": str(q_path),
             "duplicates": str(qdir / "duplicates_removed.csv"),
             "quality_report": str(_json(processed / "quality_report.json", quality)), "cleaning_log": str(log_path)}
    return finish(result, cfg, run.meta, paths)


def _whole_file_spellings(run, cfg, size) -> dict[str, dict[str, str]]:
    """First pass: count spellings of 'normalize_case' text columns over the WHOLE file, so every piece
    standardizes to the same most-common spelling (otherwise each piece would pick its own)."""
    from collections import Counter

    from insightflow.normalization.normalizer import tidy_text

    wanted = {c for c, s in cfg.columns.items() if s.type == "string" and s.normalize_case and not s.allowed_values}
    if not wanted or cfg.policies.categorical_case != "match_known":
        return {}
    nulls = set(cfg.policies.null_markers)
    counters: dict[str, Counter] = {c: Counter() for c in wanted}
    for raw, _bad in run.chunks(size):
        for col in raw.columns:
            canon = cfg.canonical_name(col)
            if canon in wanted:
                t = tidy_text(raw[col].astype("string"), cfg)
                t = t[t.notna() & ~t.isin(nulls) & t.ne("")]
                counters[canon].update(zip(t.str.lower(), t))
    out = {}
    for col, counter in counters.items():
        best: dict[str, tuple] = {}
        for (key, spelling), n in counter.items():
            cand = (-n, spelling)                          # most frequent, then alphabetical (as in-memory)
            if key not in best or cand < best[key]:
                best[key] = cand
        out[col] = {k: v[1] for k, v in best.items()}
    return out


def _whole_file_group_values(run, cfg, size, spellings) -> dict:
    """Second pass: for each fill_from_group column, the value every group (e.g. order) agrees on across
    the WHOLE file, so a blank in one piece can be filled from a row in another piece."""
    from insightflow.cleaning.cleaner import group_value_map

    cols = {c: s.group_by for c, s in cfg.columns.items() if s.missing_policy == "fill_from_group"}
    if not cols:
        return {}
    maps: dict[str, dict] = {c: {} for c in cols}
    for raw, _bad in run.chunks(size):
        if not len(raw):
            continue
        norm = normalize(raw, cfg, spellings=spellings)
        for col, group_by in cols.items():
            if col in norm.data and all(g in norm.data for g in group_by):
                group_value_map(norm.data, col, group_by, into=maps[col], spec=cfg.columns[col])
    return maps


def _without_whole_table_policies(cfg, warnings):
    """impute needs every row at once; fall back safely in chunked mode (fill_from_group is supported)."""
    changed = []
    cfg = cfg.model_copy(deep=True)
    for name, spec in cfg.columns.items():
        if spec.missing_policy == "impute":
            spec.missing_policy = "keep_and_flag" if spec.nullable else "quarantine"
            changed.append(name)
    if changed:
        warnings.append(f"chunked mode can't use impute for {changed}: blanks kept and flagged instead")
    return cfg


def _table_exists(con, name: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]).fetchone()[0])


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _copy_with_bom(con, query: str, target: Path, work: Path) -> None:
    """DuckDB COPY to a temp file, then prepend a UTF-8 BOM (Excel) while streaming it into place."""
    tmp = work / f"{target.stem}.part.csv"
    con.execute(f"COPY ({query}) TO '{tmp.as_posix()}' (HEADER, DELIMITER ',')")
    part = target.with_suffix(target.suffix + ".tmp")
    with open(part, "wb") as out, open(tmp, "rb") as src:
        out.write(b"\xef\xbb\xbf")
        shutil.copyfileobj(src, out, 1 << 20)
    part.replace(target)


__all__ = ["STREAMABLE", "run_chunked", "io"]
