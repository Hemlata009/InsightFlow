"""Split run messages into NOTES (information) and WARNINGS (something you may need to act on).

Only warnings, set-aside rows and flags make a run "completed_with_warnings". Notes never change the status.
Anything not recognised as a note is treated as a warning (safe default).
"""

from __future__ import annotations

import re

NOTE_PATTERNS = [
    r"^workbook has \d+ sheets",                # which sheet was used
    r"^hidden sheet\(s\) ignored",
    r"^header found on row \d+",                 # title rows above the header
    r"^\d+ blank row\(s\) skipped",
    r"^\d+ merged cell block\(s\) filled",
    r"^\d+-row header combined",
    r"^records taken from the",                  # JSON {"data": [...]}
    r"^nested objects flattened",
    r"^not a single JSON document; read as JSON Lines",
    r"^no column separator found; read as fixed-width",
    r"^this exact file was processed before",    # repeated upload: results are recomputed
    r"^column .* is not in the rule book; kept as text",
    r"^column '_overflow' is not in the rule book",
    r"^extra column\(s\) not in the rule book (added|removed) since the last run",
    r"^switched to chunked mode",
    r"^large file \(",
]
_NOTES = [re.compile(p) for p in NOTE_PATTERNS]


def is_note(message: str) -> bool:
    return any(p.search(message) for p in _NOTES)


def split_messages(messages: list[str]) -> tuple[list[str], list[str]]:
    notes = [m for m in messages if is_note(m)]
    warnings = [m for m in messages if not is_note(m)]
    return notes, warnings
