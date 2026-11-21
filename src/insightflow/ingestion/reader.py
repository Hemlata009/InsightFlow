"""Safe file reader for CSV and Excel (.xlsx).

Reads a file WITHOUT changing it and returns every cell as text, plus metadata about the file.
Interpreting values (numbers, dates, blanks) is the normalization stage's job, not this one's.

    result = read_file("data/raw/sales.xlsx", known_headers={"order_id", "qty"})
    result.data          # DataFrame of strings, with a `_source_row` column (row number in the file)
    result.metadata      # format, encoding, delimiter, sheet, header row, sha256, ...
    result.bad_rows      # rows that could not be read (wrong number of fields), never dropped silently
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

SOURCE_ROW = "_source_row"
UNCALCULATED = "#UNCALCULATED_FORMULA"
OVERFLOW = "_overflow"                  # extra cells beyond the header, kept as JSON text
SUPPORTED = {".csv": "csv", ".tsv": "csv", ".txt": "csv", ".xlsx": "xlsx", ".json": "json",
             ".jsonl": "jsonl", ".ndjson": "jsonl", ".parquet": "parquet", ".xml": "xml",
             ".fwf": "fwf", ".prn": "fwf"}
PARQUET_MAGIC = b"PAR1"
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
# Rough RAM needed per MB of file (text in pandas is ~10x its size on disk; xlsx is zipped)
MEMORY_FACTOR = {"csv": 10, "json": 12, "jsonl": 12, "xlsx": 40, "parquet": 15, "xml": 15, "fwf": 10}
ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"          # old .xls and password-protected .xlsx
ENCRYPTED_MARK = "EncryptedPackage".encode("utf-16-le")
DELIMITERS = [",", ";", "\t", "|"]


class IngestionError(Exception):
    """A file that cannot be read safely. `code` is stable and machine-readable."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass
class IngestOptions:
    max_file_mb: float = 50          # this PC has little RAM: refuse bigger files (chunking comes later)
    header_search_rows: int = 20     # look for the header in the first N rows
    sheet: str | None = None         # Excel: force a sheet; otherwise chosen automatically
    encoding: str | None = None      # CSV: force an encoding; otherwise detected
    delimiter: str | None = None     # CSV: force a delimiter; otherwise detected
    check_memory: bool = True        # refuse files that would not fit in the free RAM
    safety_margin_mb: float = 300    # keep this much RAM free for the rest of the PC
    min_checked_mb: float = 20       # files needing less RAM than this are never refused
    header_rows: int = 1             # 2 = a two-row header ("Revenue" over "Q1 | Q2" -> "Revenue Q1", ...)


@dataclass
class FileMetadata:
    file_name: str
    path: str
    format: str
    size_bytes: int
    sha256: str
    encoding: str | None = None
    delimiter: str | None = None
    sheet_name: str | None = None
    sheet_names: list[str] = field(default_factory=list)
    header_row: int = 1               # 1-based row number of the header in the file
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    read_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IngestResult:
    data: pd.DataFrame
    metadata: FileMetadata
    warnings: list[str] = field(default_factory=list)
    bad_rows: list[dict] = field(default_factory=list)   # {"source_row", "reason", "values"}


# ---------------------------------------------------------------- public API
def read_file(path: str | Path, *, known_headers: set[str] | None = None,
              options: IngestOptions | None = None) -> IngestResult:
    opts = options or IngestOptions()
    path = Path(path)
    if not path.is_file():
        raise IngestionError("not_found", f"file not found: {path}")

    fmt = SUPPORTED.get(path.suffix.lower())
    if fmt is None:
        raise IngestionError("unsupported_format",
                             f"'{path.suffix}' is not supported; use {', '.join(SUPPORTED)}")
    size = path.stat().st_size
    if size == 0:
        raise IngestionError("empty_file", f"{path.name} is empty (0 bytes)")
    if size > opts.max_file_mb * 2**20:
        raise IngestionError("too_large", f"{path.name} is {size / 2**20:.1f} MB > limit {opts.max_file_mb} MB")

    if opts.check_memory:
        _check_memory(size, fmt, opts, path.name)
    raw = path.read_bytes()             # read once; the file itself is never modified
    _check_signature(raw, fmt, path.name)

    meta = FileMetadata(file_name=path.name, path=str(path), format=fmt, size_bytes=size,
                        sha256=hashlib.sha256(raw).hexdigest(),
                        read_at=datetime.now().isoformat(timespec="seconds"))
    warnings: list[str] = []
    if fmt == "csv":
        rows = _csv_rows(raw, opts, meta, warnings)
    elif fmt == "xlsx":
        rows = _xlsx_rows(raw, opts, meta, warnings, known_headers)
    elif fmt in ("json", "jsonl"):
        rows, bad = _json_rows(raw, fmt, meta, warnings)
        return _build(rows, meta, warnings, known_headers, opts, header_index=0, extra_bad=bad)
    elif fmt == "xml":
        rows = _xml_rows(raw, meta, warnings)
        return _build(rows, meta, warnings, known_headers, opts, header_index=0)
    elif fmt == "fwf":
        rows = _fwf_rows(raw, opts, meta, warnings)
    else:
        rows = _parquet_rows(raw, meta)
        return _build(rows, meta, warnings, known_headers, opts, header_index=0)
    return _build(rows, meta, warnings, known_headers, opts)


def _check_memory(size: int, fmt: str, opts: IngestOptions, name: str) -> None:
    try:
        import psutil
    except ImportError:                  # psutil missing: skip the check rather than block
        return
    need = size / 2**20 * MEMORY_FACTOR.get(fmt, 10)
    if need < opts.min_checked_mb:       # tiny files can't hurt; don't refuse them when the PC is busy
        return
    free = psutil.virtual_memory().available / 2**20
    if need > free - opts.safety_margin_mb:
        raise IngestionError("insufficient_memory",
                             f"{name} needs about {need:.0f} MB of RAM to read, but only {free:.0f} MB is free "
                             f"(keeping {opts.safety_margin_mb:.0f} MB for the PC). Close other programs or split the file")


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- checks
def _check_signature(raw: bytes, fmt: str, name: str) -> None:
    head = raw[:8]
    if fmt == "xlsx":
        if head.startswith(OLE_MAGIC):
            if ENCRYPTED_MARK in raw:
                raise IngestionError("encrypted_file", f"{name} is password-protected; save it without a password")
            raise IngestionError("unsupported_format", f"{name} is an old .xls workbook; save it as .xlsx")
        if not head.startswith(ZIP_MAGIC):
            raise IngestionError("signature_mismatch", f"{name} is named .xlsx but is not an Excel file")
    elif fmt == "parquet":
        if not (raw.startswith(PARQUET_MAGIC) and raw.endswith(PARQUET_MAGIC)):
            raise IngestionError("signature_mismatch", f"{name} is named .parquet but is not a Parquet file")
    else:
        if raw.startswith(UTF16_BOMS):
            return                       # UTF-16 text (Excel "Unicode Text" export): zero bytes are normal
        if head.startswith(ZIP_MAGIC) or head.startswith(OLE_MAGIC) or raw.startswith(PARQUET_MAGIC) \
                or b"\x00" in raw[:4096]:
            raise IngestionError("signature_mismatch", f"{name} contains binary data, not text "
                                                       "(maybe an Excel/Parquet file with the wrong extension)")


# ---------------------------------------------------------------- CSV
def _decode(raw: bytes, forced: str | None) -> tuple[str, str]:
    if forced:
        try:
            return raw.decode(forced), forced
        except UnicodeDecodeError as e:
            raise IngestionError("encoding_error", f"cannot decode with {forced}: {e}") from e
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    if raw.startswith(UTF16_BOMS):
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError as e:
            raise IngestionError("encoding_error", f"looks like UTF-16 but cannot be decoded: {e}") from e
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"          # never fails; reported so a human can check


def _detect_delimiter(text: str) -> str:
    """Pick the delimiter that splits the first lines into the most consistent number (>1) of fields."""
    sample = "\n".join(text.splitlines()[:50])
    best, best_score = None, (-1, 0)
    for d in DELIMITERS:
        counts = [len(r) for r in csv.reader(io.StringIO(sample), delimiter=d) if any(c.strip() for c in r)]
        if not counts:
            continue
        mode = max(set(counts), key=counts.count)
        if mode < 2:
            continue
        score = (counts.count(mode), mode)            # most rows agreeing, then most columns
        if score > best_score:
            best, best_score = d, score
    return best


def _csv_rows(raw, opts, meta, warnings) -> list[tuple[int, list[str]]]:
    text, enc = _decode(raw, opts.encoding)
    meta.encoding = enc
    if enc == "latin-1":
        warnings.append("encoding not recognised; read as latin-1. Check special characters")
    if not text.strip():
        raise IngestionError("empty_file", f"{meta.file_name} contains only blank space")
    meta.delimiter = opts.delimiter or _detect_delimiter(text)
    if meta.delimiter is None:                        # nothing splits the lines: maybe fixed-width text
        warnings.append("no column separator found; read as fixed-width columns")
        meta.format = "fwf"
        return _fwf_text_rows(text, meta)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=meta.delimiter)
    rows = []
    try:
        for record in reader:
            rows.append((reader.line_num, record))   # line_num = file line where the record ends
    except csv.Error as e:
        raise IngestionError("corrupt_file", f"CSV parse error near line {reader.line_num}: {e}") from e
    return rows


# ---------------------------------------------------------------- Excel
def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.isoformat(sep=" ") if (v.hour or v.minute or v.second) else v.date().isoformat()
    if isinstance(v, (date, time)):
        return v.isoformat()
    return str(v)


def _xlsx_rows(raw, opts, meta, warnings, known_headers) -> list[tuple[int, list[str]]]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as e:
        raise IngestionError("corrupt_file", f"{meta.file_name} could not be opened: {e}") from e
    try:
        meta.sheet_names = list(wb.sheetnames)
        hidden = {n for n in wb.sheetnames if getattr(wb[n], "sheet_state", "visible") != "visible"}
        sheets = {}
        for name in wb.sheetnames:
            rows = [(i, [_cell_text(v) for v in r])
                    for i, r in enumerate(wb[name].iter_rows(values_only=True), start=1)]
            sheets[name] = rows
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as e:
        raise IngestionError("corrupt_file", f"{meta.file_name} is damaged: {e}") from e
    finally:
        wb.close()

    if opts.sheet:
        if opts.sheet not in sheets:
            raise IngestionError("sheet_not_found", f"sheet {opts.sheet!r} not in {meta.sheet_names}")
        chosen = opts.sheet
    else:
        visible = [n for n in meta.sheet_names if n not in hidden] or meta.sheet_names
        if hidden:
            warnings.append(f"hidden sheet(s) ignored: {sorted(hidden)}")
        if len(visible) == 1:
            chosen = visible[0]
        else:
            chosen = max(visible, key=lambda n: _sheet_score(sheets[n], known_headers, opts))
            warnings.append(f"workbook has {len(visible)} sheets {visible}; using {chosen!r}")
    meta.sheet_name = chosen
    if not any(any(c.strip() for c in r) for _, r in sheets[chosen]):
        raise IngestionError("empty_sheet", f"sheet {chosen!r} is empty")
    rows = sheets[chosen]
    sheet_xml = _sheet_xml(raw, meta.sheet_names.index(chosen))
    if b"<mergeCell " in sheet_xml:
        rows = _fill_merged(raw, chosen, rows, warnings)
    if b"<f" in sheet_xml:
        rows = _mark_uncalculated(raw, chosen, rows, warnings)
    return rows


def _sheet_xml(raw: bytes, index: int) -> bytes:
    """Raw XML of the n-th worksheet (cheap check for merged cells / formulas without loading everything)."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        import re as _re
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
        wbx = z.read("xl/workbook.xml").decode("utf-8", "replace")
        rids = _re.findall(r'<sheet\b[^>]*?r:id="([^"]+)"', wbx)
        if index >= len(rids):
            return b""
        m = _re.search(r'<Relationship\b[^>]*Id="%s"[^>]*Target="([^"]+)"' % _re.escape(rids[index]), rels) or \
            _re.search(r'<Relationship\b[^>]*Target="([^"]+)"[^>]*Id="%s"' % _re.escape(rids[index]), rels)
        if not m:
            return b""
        target = m.group(1).lstrip("/")
        target = target if target.startswith("xl/") else f"xl/{target}"
        return z.read(target) if target in z.namelist() else b""


def _fill_merged(raw, sheet, rows, warnings):
    """Copy the top-left value of every merged block into all its cells (openpyxl's merged ranges)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=False, data_only=True)
    try:
        ranges = list(wb[sheet].merged_cells.ranges)
    finally:
        wb.close()
    grid = {n: list(r) for n, r in rows}
    for rng in ranges:
        top = grid.get(rng.min_row, [])
        value = top[rng.min_col - 1] if len(top) >= rng.min_col else ""
        for r in range(rng.min_row, rng.max_row + 1):
            cells = grid.setdefault(r, [])
            if len(cells) < rng.max_col:
                cells.extend([""] * (rng.max_col - len(cells)))
            for c in range(rng.min_col, rng.max_col + 1):
                cells[c - 1] = value
    warnings.append(f"{len(ranges)} merged cell block(s) filled with their top-left value")
    return [(n, grid[n]) for n, _ in rows]


def _mark_uncalculated(raw, sheet, rows, warnings):
    """A formula saved without its result (files written by tools, not Excel) reads as blank. Mark it."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
    try:
        formulas = {i: [v if isinstance(v, str) and v.startswith("=") else None for v in r]
                    for i, r in enumerate(wb[sheet].iter_rows(values_only=True), start=1)}
    finally:
        wb.close()
    grid = {n: cells for n, cells in rows}
    count, calculated, out = 0, 0, []
    for n, cells in rows:
        f = formulas.get(n, [])
        new = list(cells)
        for j, v in enumerate(new):
            if j < len(f) and f[j] and not v.strip():
                value = _evaluate_formula(f[j], grid)
                if value is None:
                    new[j] = UNCALCULATED
                    count += 1
                else:
                    new[j] = value
                    calculated += 1
        out.append((n, new))
    if calculated:
        warnings.append(f"{calculated} formula cell(s) had no saved result and were calculated by InsightFlow "
                        "(simple arithmetic of cells only); worth a check")
    if count:
        warnings.append(f"{count} formula cell(s) have no saved result (the file was never recalculated); "
                        "those rows are set aside. Open and save the file in Excel or LibreOffice to fix")
    return out


_REF = r"\$?([A-Z]{1,3})\$?(\d+)"


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _evaluate_formula(formula: str, grid: dict) -> str | None:
    """'=H5*I5*(1-K5)' -> '180'. Only numbers, same-sheet cell references and + - * / ( ).
    Anything else (functions, other sheets, text, empty or uncalculated cells) -> None (not guessed)."""
    import re as _re

    from insightflow.money import evaluate

    body = formula[1:] if formula.startswith("=") else formula
    if not _re.fullmatch(r"[A-Z$\d\s.+\-*/()]+", body):
        return None
    values = {}

    def name(m):
        col, row = m.group(1), int(m.group(2))
        cells = grid.get(row, [])
        j = _col_index(col)
        text = cells[j].strip() if j < len(cells) else ""
        try:
            float(text)
        except ValueError:
            raise LookupError from None
        key = f"c_{col}{row}"
        values[key] = text
        return key

    try:
        expr = _re.sub(_REF, name, body)
        result = evaluate(expr, values)
    except (LookupError, ValueError, SyntaxError):
        return None
    if result is None:
        return None
    return format(result.normalize(), "f")


def _sheet_score(rows, known_headers, opts) -> tuple:
    nonempty = [r for _, r in rows if any(c.strip() for c in r)]
    width = max((sum(1 for c in r if c.strip()) for r in nonempty), default=0)
    idx = _find_header(rows, known_headers, opts.header_search_rows)
    matches = _header_matches(rows[idx][1], known_headers) if idx is not None else 0
    return (matches, width * len(nonempty))


# ---------------------------------------------------------------- JSON / JSON Lines
def _json_rows(raw, fmt, meta, warnings):
    """Records -> (rows, bad_rows). Nested objects are flattened to dotted columns; lists stay JSON text."""
    import json

    text, enc = _decode(raw, None)
    meta.encoding = enc
    if not text.strip():
        raise IngestionError("empty_file", f"{meta.file_name} contains only blank space")
    records, numbers, bad = None, None, []
    if fmt == "json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
            warnings.append("not a single JSON document; read as JSON Lines (one object per line)")
        if doc is not None:
            if isinstance(doc, dict):
                lists = [k for k, v in doc.items() if isinstance(v, list) and v and isinstance(v[0], dict)]
                if len(lists) != 1:
                    raise IngestionError("unsupported_json", "a JSON object must hold exactly one list of "
                                                             f"records (found {len(lists)})")
                warnings.append(f"records taken from the {lists[0]!r} key")
                doc = doc[lists[0]]
            if not isinstance(doc, list) or not all(isinstance(d, dict) for d in doc):
                raise IngestionError("unsupported_json", "JSON must be a list of objects (records)")
            records, numbers = doc, list(range(1, len(doc) + 1))
    if records is None:                    # JSON Lines
        records, numbers = [], []
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                obj = None
            if not isinstance(obj, dict):
                bad.append({"source_row": n, "reason": "not a JSON object", "values": [line[:200]]})
                continue
            records.append(obj)
            numbers.append(n)
    if not records:
        raise IngestionError("no_data_rows", f"{meta.file_name} has no records")

    frame = pd.json_normalize(records, sep=".")
    nested = [c for c in frame.columns if frame[c].map(lambda v: isinstance(v, (list, dict))).any()]
    if nested:
        warnings.append(f"column(s) {nested} hold lists; kept as JSON text (not flattened)")
    dotted = [c for c in frame.columns if "." in c]
    if dotted:
        warnings.append(f"nested objects flattened into dotted columns, e.g. {dotted[:3]}")
    if len({tuple(sorted(r)) for r in records}) > 1:
        warnings.append("records do not all have the same keys; missing keys become blanks")
    out = [(0, [str(c) for c in frame.columns])]
    for n, rec in zip(numbers, frame.itertuples(index=False)):
        out.append((n, [_json_text(v) for v in rec]))
    return out, bad


def json_dumps(v) -> str:
    import json
    return json.dumps(v, ensure_ascii=False)


def _json_text(v) -> str:
    import json
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if hasattr(v, "to_pydatetime"):
        v = v.to_pydatetime()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()                       # numpy scalar -> Python
    return _cell_text(v)


# ---------------------------------------------------------------- Parquet
def _parquet_rows(raw, meta) -> list[tuple[int, list[str]]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise IngestionError("unsupported_format", "reading Parquet needs the 'pyarrow' package") from e
    try:
        frame = pq.read_table(io.BytesIO(raw)).to_pandas()
    except Exception as e:  # noqa: BLE001 - any pyarrow failure means a damaged file
        raise IngestionError("corrupt_file", f"{meta.file_name} could not be read as Parquet: {e}") from e
    out = [(0, [str(c) for c in frame.columns])]
    for n, rec in enumerate(frame.itertuples(index=False), start=1):
        out.append((n, [_json_text(v) for v in rec]))
    return out


# ---------------------------------------------------------------- XML (defusedxml: safe against XML bombs)
def _xml_rows(raw, meta, warnings):
    try:
        from defusedxml import ElementTree as SafeET
        from defusedxml.common import DefusedXmlException
    except ImportError as e:
        raise IngestionError("unsupported_format", "reading XML needs the 'defusedxml' package") from e
    try:
        root = SafeET.fromstring(raw)
    except DefusedXmlException as e:
        raise IngestionError("unsafe_xml", f"{meta.file_name} uses XML features that can be abused: {e}") from e
    except Exception as e:  # noqa: BLE001 - any parse error = damaged file
        raise IngestionError("corrupt_file", f"{meta.file_name} is not valid XML: {e}") from e
    records = []
    for el in list(root):
        rec = {f"@{k}": v for k, v in el.attrib.items()}
        for child in list(el):
            tag = child.tag.split("}")[-1]
            if len(child):                               # nested element: keep as JSON text
                rec[tag] = {g.tag.split("}")[-1]: (g.text or "").strip() for g in child}
            else:
                rec[tag] = (child.text or "").strip()
        records.append(rec)
    if not records:
        raise IngestionError("no_data_rows", f"{meta.file_name} has no records under the root element")
    meta.encoding = "xml-declared"
    import json
    rows, _bad = _json_rows(json.dumps(records).encode("utf-8"), "json", meta, warnings)
    meta.encoding = "xml-declared"
    return rows


# ---------------------------------------------------------------- fixed-width text (pandas.read_fwf)
def _fwf_rows(raw, opts, meta, warnings):
    text, enc = _decode(raw, opts.encoding)
    meta.encoding = enc
    return _fwf_text_rows(text, meta)


def _fwf_text_rows(text, meta):
    lines = [(n, line) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if not lines:
        raise IngestionError("empty_file", f"{meta.file_name} has no content")
    frame = pd.read_fwf(io.StringIO("\n".join(line for _, line in lines)), colspecs="infer", header=None,
                        dtype=str, keep_default_na=False, infer_nrows=min(len(lines), 500))
    meta.delimiter = "fixed-width"
    return [(n, [str(v).strip() for v in rec]) for (n, _), rec in zip(lines, frame.itertuples(index=False))]


# ---------------------------------------------------------------- header + frame
def _norm(text: str) -> str:
    from insightflow.config import normalize_header
    return normalize_header(text)


def _header_matches(cells, known_headers) -> int:
    if not known_headers:
        return 0
    return sum(1 for c in cells if c.strip() and _norm(c) in known_headers)


def _looks_numeric(s: str) -> bool:
    try:
        float(s.replace(",", "").strip())
        return True
    except ValueError:
        return False


def _find_header(rows, known_headers, search) -> int | None:
    """Index (into rows) of the header row: the best match to known headers, else the first wide row
    of non-numeric text."""
    window = rows[:search]
    if not window:
        return None
    width = max((sum(1 for c in r if c.strip()) for _, r in window), default=0)
    if known_headers:
        scored = [(_header_matches(r, known_headers), -i, i) for i, (_, r) in enumerate(window)]
        best = max(scored)
        if best[0] >= 2:
            return best[2]
    for i, (_, r) in enumerate(window):
        filled = [c for c in r if c.strip()]
        if len(filled) >= max(2, width * 0.6) and not any(_looks_numeric(c) for c in filled):
            return i
    return None


def _build(rows, meta, warnings, known_headers, opts, header_index: int | None = None,
           extra_bad: list[dict] | None = None) -> IngestResult:
    rows = [(n, r) for n, r in rows]
    if not any(any(c.strip() for c in r) for _, r in rows):
        raise IngestionError("empty_file", f"{meta.file_name} has no content")
    idx = header_index if header_index is not None else _find_header(rows, known_headers,
                                                                        opts.header_search_rows)
    if idx is None:
        raise IngestionError("no_header_found",
                             f"no header row found in the first {opts.header_search_rows} rows")
    header_line, header = rows[idx]
    if opts.header_rows > 1:
        extra = rows[idx + 1: idx + opts.header_rows]
        width = max(len(header), *(len(r) for _, r in extra))
        parts = [list(header) + [""] * (width - len(header))] + [list(r) + [""] * (width - len(r)) for _, r in extra]
        header = [" ".join(dict.fromkeys(p[j].strip() for p in parts if p[j].strip())) for j in range(width)]
        rows = rows[:idx + 1] + rows[idx + opts.header_rows:]
        warnings.append(f"{opts.header_rows}-row header combined, e.g. {[h for h in header if ' ' in h][:3]}")
    meta.header_row = header_line
    if idx > 0:
        warnings.append(f"header found on row {header_line}; {idx} row(s) above it skipped")

    # Trailing empty header cells are padding only if no data row uses those columns.
    used = max((max((j + 1 for j, c in enumerate(r) if c.strip()), default=0)
                for _, r in rows[idx + 1:]), default=0)
    while header and not header[-1].strip() and len(header) > used:
        header = header[:-1]
    columns, seen = [], {}
    for i, h in enumerate(header, start=1):
        name = h if h.strip() else f"unnamed_{i}"    # keep the raw header text; mapping is Step 5
        if not h.strip():
            warnings.append(f"column {i} has no header; named {name!r}")
        if name in seen:
            seen[name] += 1
            new = f"{name}__{seen[name]}"
            warnings.append(f"duplicate column name {name!r}; renamed to {new!r}")
            name = new
        else:
            seen[name] = 1
        columns.append(name)

    data, bad, blank = [], list(extra_bad or []), 0
    overflow: dict[int, str] = {}
    width = len(columns)
    for line, r in rows[idx + 1:]:
        if not any(c.strip() for c in r):
            blank += 1
            continue
        if len(r) > width and not any(c.strip() for c in r[width:]):
            r = r[:width]                             # extra empty cells at the end are harmless
        if meta.format == "xlsx" and len(r) < width:
            r = r + [""] * (width - len(r))           # Excel omits trailing empty cells
        if len(r) > width and meta.format != "xlsx":      # extra cells at the END: keep them aside
            extra = [c for c in r[width:]]
            r = r[:width]
            overflow[line] = json_dumps(extra)
        if len(r) != width:
            bad.append({"source_row": line, "reason": f"{len(r)} fields, expected {width}", "values": r})
            continue
        if UNCALCULATED in r:
            cols = [columns[j] for j, v in enumerate(r) if v == UNCALCULATED]
            bad.append({"source_row": line, "reason": f"uncalculated formula in {cols}", "values": r})
            continue
        data.append([line, *r])
    if blank:
        warnings.append(f"{blank} blank row(s) skipped")
    if bad:
        warnings.append(f"{len(bad)} row(s) with the wrong number of fields set aside")
    if not data:
        raise IngestionError("no_data_rows", f"{meta.file_name} has a header but no data rows")

    df = pd.DataFrame(data, columns=[SOURCE_ROW, *columns])
    df[columns] = df[columns].astype("string")
    if overflow:
        df[OVERFLOW] = pd.array([overflow.get(r) for r in df[SOURCE_ROW]], dtype="string")
        warnings.append(f"{len(overflow)} row(s) had more cells than the header; the extra cells are kept in "
                        f"column '{OVERFLOW}' and the rows are flagged")
        columns = [*columns, OVERFLOW]
    meta.rows, meta.columns = len(df), columns
    return IngestResult(df, meta, warnings, bad)
