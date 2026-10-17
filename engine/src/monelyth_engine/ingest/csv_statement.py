"""Import bank statements saved as CSV.

CSV has no standard layout, so importing takes two steps:

1. :func:`detect_csv` guesses the layout and lists what it couldn't decide, for the UI to ask.
2. :func:`parse_csv` reads every row with the layout the user confirmed.

The confirmed layout is saved per bank (``CsvLayout.to_dict()``, keyed by
``CsvDetection.header_signature``), so the next import from the same bank needs no questions.

This module is the public face of the CSV importer; the work happens in the ``csv_*`` modules
it imports from.
"""

from __future__ import annotations

from monelyth_engine.ingest.csv_detect import (
    PREVIEW_ROWS,
    CsvDetection,
    CsvQuestion,
    CsvQuestionKind,
    detect_csv,
    header_signature,
)
from monelyth_engine.ingest.csv_layout import (
    AmountColumns,
    CsvLayout,
    CsvLayoutDraft,
    CsvLayoutError,
    DebitCredit,
    Delimiter,
    Encoding,
    SignedAmount,
)
from monelyth_engine.ingest.csv_parse import parse_csv
from monelyth_engine.ingest.csv_reader import MAX_FILE_BYTES, MAX_ROWS
from monelyth_engine.ingest.csv_values import DATE_FORMATS, DecimalSeparator, date_format_label

__all__ = [
    "DATE_FORMATS",
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "PREVIEW_ROWS",
    "AmountColumns",
    "CsvDetection",
    "CsvLayout",
    "CsvLayoutDraft",
    "CsvLayoutError",
    "CsvQuestion",
    "CsvQuestionKind",
    "DebitCredit",
    "DecimalSeparator",
    "Delimiter",
    "Encoding",
    "SignedAmount",
    "date_format_label",
    "detect_csv",
    "header_signature",
    "parse_csv",
]
