"""InsightFlow ingestion stage: read CSV/Excel files safely, as text, with metadata."""

from .reader import (SOURCE_ROW, FileMetadata, IngestionError, IngestOptions, IngestResult,
                     file_sha256, read_file)
from .registry import FileRegistry

__all__ = ["SOURCE_ROW", "FileMetadata", "FileRegistry", "IngestionError", "IngestOptions",
           "IngestResult", "file_sha256", "read_file"]
