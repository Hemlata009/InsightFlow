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
SUPPORTED = {".csv": "csv", ".xlsx": "xlsx"}
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

    raw = path.read_bytes()             # read once; the file itself is never modified
    _check_signature(raw, fmt, path.name)

    meta = FileMetadata(file_name=path.name, path=str(path), format=fmt, size_bytes=size,
                        sha256=hashlib.sha256(raw).hexdigest(),
                        read_at=datetime.now().isoformat(timespec="seconds"))
    warnings: list[str] = []
    if fmt == "csv":
        rows = _csv_rows(raw, opts, meta, warnings)
    else:
        rows = _xlsx_rows(raw, opts, meta, warnings, known_headers)
    return _build(rows, meta, warnings, known_headers, opts)


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
    else:
        if head.startswith(ZIP_MAGIC) or head.startswith(OLE_MAGIC) or b"\x00" in raw[:4096]:
            raise IngestionError("signature_mismatch", f"{name} is named .csv but contains binary data "
                                                       "(maybe an Excel file with the wrong extension)")


# ---------------------------------------------------------------- CSV
def _decode(raw: bytes, forced: str | None) -> tuple[str, str]:
    if forced:
        try:
            return raw.decode(forced), forced
        except UnicodeDecodeError as e:
            raise IngestionError("encoding_error", f"cannot decode with {forced}: {e}") from e
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"          # never fails; reported so a human can check


def _detect_delimiter(text: str) -> str:
    """Pick the delimiter that splits the first lines into the most consistent number (>1) of fields."""
    sample = "\n".join(text.splitlines()[:50])
    best, best_score = ",", (-1, 0)
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
    elif len(sheets) == 1:
        chosen = meta.sheet_names[0]
    else:
        chosen = max(sheets, key=lambda n: _sheet_score(sheets[n], known_headers, opts))
        warnings.append(f"workbook has {len(sheets)} sheets {meta.sheet_names}; using {chosen!r}")
    meta.sheet_name = chosen
    if not any(any(c.strip() for c in r) for _, r in sheets[chosen]):
        raise IngestionError("empty_sheet", f"sheet {chosen!r} is empty")
    return sheets[chosen]


def _sheet_score(rows, known_headers, opts) -> tuple:
    nonempty = [r for _, r in rows if any(c.strip() for c in r)]
    width = max((sum(1 for c in r if c.strip()) for r in nonempty), default=0)
    idx = _find_header(rows, known_headers, opts.header_search_rows)
    matches = _header_matches(rows[idx][1], known_headers) if idx is not None else 0
    return (matches, width * len(nonempty))


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


def _build(rows, meta, warnings, known_headers, opts) -> IngestResult:
    rows = [(n, r) for n, r in rows]
    if not any(any(c.strip() for c in r) for _, r in rows):
        raise IngestionError("empty_file", f"{meta.file_name} has no content")
    idx = _find_header(rows, known_headers, opts.header_search_rows)
    if idx is None:
        raise IngestionError("no_header_found",
                             f"no header row found in the first {opts.header_search_rows} rows")
    header_line, header = rows[idx]
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

    data, bad, blank = [], [], 0
    width = len(columns)
    for line, r in rows[idx + 1:]:
        if not any(c.strip() for c in r):
            blank += 1
            continue
        if len(r) > width and not any(c.strip() for c in r[width:]):
            r = r[:width]                             # extra empty cells at the end are harmless
        if meta.format == "xlsx" and len(r) < width:
            r = r + [""] * (width - len(r))           # Excel omits trailing empty cells
        if len(r) != width:
            bad.append({"source_row": line, "reason": f"{len(r)} fields, expected {width}", "values": r})
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
    meta.rows, meta.columns = len(df), columns
    return IngestResult(df, meta, warnings, bad)
