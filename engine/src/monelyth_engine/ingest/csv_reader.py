"""Turn the bytes of a CSV file into rows, safely.

The file comes from the user's bank, but it is still untrusted input: it could be huge, binary,
or built to exhaust memory. Every limit is checked here, before any parsing work, and every
problem becomes a :class:`StatementParseError` with a message the user can act on.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from typing import Final

from monelyth_engine.ingest.csv_layout import ENCODINGS, MAX_COLUMNS, Delimiter, Encoding
from monelyth_engine.ingest.models import StatementParseError

MAX_FILE_BYTES: Final = 20 * 1024 * 1024
"""Largest file accepted. Years of transactions fit in a few megabytes."""
MAX_ROWS: Final = 100_000
"""Most rows read from one file, counting blank ones, which bounds time and memory."""

_ENCODING_NAMES: Final[dict[Encoding, str]] = {"utf-8-sig": "UTF-8", "cp1252": "Windows-1252"}
_PDF_MAGIC: Final = b"%PDF-"
_ZIP_MAGIC: Final = b"PK\x03\x04"
"""Excel's .xlsx (and every other zip-based format) starts with this."""
_OLE_MAGIC: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
"""Excel's older .xls format starts with this."""
_UTF16_BOMS: Final = (b"\xff\xfe", b"\xfe\xff")
_LINE: Final = re.compile(r"[^\r\n]*(?:\r\n?|\n)?")
"""One line with its ending, split on the same line endings as a file opened with
``newline=""``."""
_MAX_DELIMITERS_PER_LINE: Final = 16 * MAX_COLUMNS
"""More delimiters than this on one line can't be a statement row, even with some inside quotes.
Checked before the csv module splits the line, so a line of millions of commas never becomes a
list of millions of cells."""


def decode_detected(data: bytes) -> tuple[str, Encoding]:
    """Decode a file with the first supported encoding that reads it without errors.

    UTF-8 is tried first because a Windows-1252 file is almost never valid UTF-8, while most
    byte sequences are valid Windows-1252.
    """
    _check_bytes(data)
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise StatementParseError(
        "The file's text encoding isn't supported. Save it as \"CSV UTF-8\" and try again."
    )


def decode(data: bytes, encoding: Encoding) -> str:
    """Decode a file with the encoding a layout names."""
    _check_bytes(data)
    try:
        return data.decode(encoding)
    except UnicodeDecodeError as error:
        raise StatementParseError(
            f"The file isn't valid {_ENCODING_NAMES[encoding]} text. Import it again so "
            "Monelyth can detect its encoding."
        ) from error


def iter_rows(text: str, delimiter: Delimiter) -> Iterator[tuple[int, list[str]]]:
    """Yield ``(row_number, cells)`` for every CSV record, numbering rows from 1.

    A quoted value may contain line breaks, so a row is a record, not a line: the same numbering
    a spreadsheet shows, which is what error messages refer to.

    Raises:
        StatementParseError: if a row can't be read as CSV, has more than :data:`MAX_COLUMNS`
            cells, or the file has more than :data:`MAX_ROWS` rows.
    """
    row_number = 0

    def lines() -> Iterator[str]:
        # Lines are cut from the text one at a time: io.StringIO would hold a second copy of
        # the whole file at four bytes per character.
        for match in _LINE.finditer(text):
            line = match.group()
            if not line:
                continue  # The empty match at the very end of the text.
            if line.count(delimiter) > _MAX_DELIMITERS_PER_LINE:
                raise StatementParseError(
                    f"Row {row_number} has far more than the {MAX_COLUMNS} columns a statement "
                    "can have. Check that this is a bank statement saved as CSV."
                )
            yield line

    # skipinitialspace reads `a, "b, c"` as two cells, the way spreadsheets do.
    reader = csv.reader(lines(), delimiter=delimiter, skipinitialspace=True)
    while True:
        row_number += 1
        try:
            cells = next(reader)
        except StopIteration:
            return
        except csv.Error as error:
            raise StatementParseError(
                f"Row {row_number} can't be read: one of its values is too long, which usually "
                "means a quote mark is never closed."
                if "field larger than field limit" in str(error)
                else f"Row {row_number} can't be read as CSV ({error})."
            ) from error
        if row_number > MAX_ROWS:
            raise StatementParseError(
                f"The file has more than {MAX_ROWS:,} rows. Export a shorter date range and "
                "import each part separately."
            )
        if len(cells) > MAX_COLUMNS:
            raise StatementParseError(
                f"Row {row_number} has {len(cells):,} columns, more than the {MAX_COLUMNS} a "
                "statement can have. Check that this is a bank statement saved as CSV."
            )
        yield row_number, cells


def cell_at(cells: list[str], column: int) -> str:
    """A row's cell, or an empty string when a short row stops before ``column``."""
    return cells[column] if column < len(cells) else ""


def _check_bytes(data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise StatementParseError(
            f"The file is {len(data) / 1024 / 1024:.1f} MB; the most Monelyth reads is "
            f"{MAX_FILE_BYTES // 1024 // 1024} MB. Export a shorter date range and import each "
            "part separately."
        )
    if not data or data.isspace():
        raise StatementParseError("The file is empty.")
    if data.startswith(_PDF_MAGIC):
        raise StatementParseError(
            "This is a PDF, not a CSV file. Download the CSV version of the statement from your "
            "bank instead."
        )
    if data.startswith((_ZIP_MAGIC, _OLE_MAGIC)):
        raise StatementParseError(
            "This looks like an Excel workbook, not a CSV file. Open it in Excel and save it "
            'as "CSV UTF-8", or download the CSV version from your bank.'
        )
    if data.startswith(_UTF16_BOMS):
        raise StatementParseError(
            'The file is saved as UTF-16 text, which isn\'t supported. Save it as "CSV UTF-8" '
            "and try again."
        )
    if b"\x00" in data:
        raise StatementParseError("This isn't a text file, so it can't be a CSV statement.")
