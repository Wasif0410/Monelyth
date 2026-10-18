"""Importing a statement file: first preview what it contains, then store it.

The two steps match the UI. :func:`preview_import` reads the file without saving anything and
reports what the user still has to confirm (for CSV, the column layout). :func:`commit_import`
stores the transactions once the user has confirmed, deduplicating against earlier imports.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PureWindowsPath
from typing import Final

from monelyth_engine.db.accounts import get_account
from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.csv_profiles import get_csv_profile, save_csv_profile
from monelyth_engine.db.imports import find_import, record_import
from monelyth_engine.db.models import ImportRecord, NewTransaction
from monelyth_engine.db.transactions import insert_transactions
from monelyth_engine.ingest.csv_statement import (
    MAX_FILE_BYTES as CSV_MAX_FILE_BYTES,
)
from monelyth_engine.ingest.csv_statement import (
    PREVIEW_ROWS,
    CsvLayout,
    CsvLayoutDraft,
    CsvLayoutError,
    CsvQuestion,
    detect_csv,
    parse_csv,
)
from monelyth_engine.ingest.models import (
    ParsedStatement,
    RawTransaction,
    StatementFormat,
    StatementParseError,
)
from monelyth_engine.ingest.ofx_statement import MAX_FILE_BYTES as OFX_MAX_FILE_BYTES
from monelyth_engine.ingest.ofx_statement import parse_ofx
from monelyth_engine.normalize import normalize_merchant

MAX_UPLOAD_BYTES: Final = max(CSV_MAX_FILE_BYTES, OFX_MAX_FILE_BYTES)
MAX_FILE_NAME_LENGTH: Final = 255
_FALLBACK_FILE_NAME: Final = "statement"
_OFX_SNIFF_BYTES: Final = 4096
"""OFX announces itself in its first few lines: an ``OFXHEADER:`` line (1.x) or an
``<?OFX ...?>`` processing instruction and ``<OFX>`` root (2.x)."""
_OFX_MARKERS: Final = (b"ofxheader:", b"<?ofx", b"<ofx>")
_LAYOUT_FOR_NON_CSV: Final = "A column layout only applies to CSV files."

logger = logging.getLogger(__name__)


class ImportRequestError(ValueError):
    """The request can't be carried out as asked. The message is shown to the user."""


class FileTooLargeError(ImportRequestError):
    """The uploaded file is bigger than any statement the importers accept."""


class LayoutSource(StrEnum):
    SAVED = "saved"
    """Taken from the layout the user confirmed for this bank's header before."""
    DETECTED = "detected"
    """Guessed from this file; the user should confirm it."""
    CHOSEN = "chosen"
    """Sent with the request: the layout the user is choosing in the UI."""


@dataclass(frozen=True, slots=True)
class StatementFile:
    """An uploaded file. The name is only for display; the content decides the format."""

    name: str
    data: bytes

    @classmethod
    def from_upload(cls, file_name: str | None, data: bytes) -> StatementFile:
        """Build from an upload, keeping only the base name of whatever path the client sent.

        Raises:
            FileTooLargeError: if ``data`` is larger than :data:`MAX_UPLOAD_BYTES`.
        """
        if len(data) > MAX_UPLOAD_BYTES:
            raise FileTooLargeError(
                f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB, which is "
                "bigger than any bank statement. Check that it is the right file."
            )
        # PureWindowsPath splits on both "/" and "\", so this also strips POSIX-style paths.
        name = PureWindowsPath(file_name or "").name.strip()[:MAX_FILE_NAME_LENGTH]
        return cls(name=name or _FALLBACK_FILE_NAME, data=data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True, slots=True)
class PreviewRow:
    transaction: RawTransaction
    merchant: str
    """The cleaned merchant name the transaction will be stored with."""


@dataclass(frozen=True, slots=True)
class CsvPreview:
    layout: CsvLayoutDraft
    layout_source: LayoutSource
    columns: tuple[str, ...]
    questions: tuple[CsvQuestion, ...]
    """Empty when the layout is complete and reads every row."""


@dataclass(frozen=True, slots=True)
class ImportPreview:
    format: StatementFormat
    file_name: str
    rows: tuple[PreviewRow, ...]
    """The first few transactions, to show the user what will be imported."""
    transaction_count: int | None
    """How many transactions the file holds, or ``None`` until a CSV layout reads every row."""
    currency: str | None
    warnings: tuple[str, ...]
    previous_import: ImportRecord | None
    """Set when this exact file was imported before; committing it again will be refused."""
    csv: CsvPreview | None
    """Present for CSV files only."""


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    record: ImportRecord
    added: int
    skipped_duplicates: int
    warnings: tuple[str, ...]


def detect_format(data: bytes) -> StatementFormat:
    """OFX and QFX files identify themselves near the top; anything else is treated as CSV."""
    head = data[:_OFX_SNIFF_BYTES].lower()
    return (
        StatementFormat.OFX
        if any(marker in head for marker in _OFX_MARKERS)
        else (StatementFormat.CSV)
    )


def preview_import(
    conn: sqlite3.Connection, file: StatementFile, layout: CsvLayout | None = None
) -> ImportPreview:
    """Read ``file`` without storing anything.

    For a CSV whose header matches a layout the user confirmed before, that layout is used, so
    a returning bank needs no questions. If the saved layout no longer reads the file (the bank
    changed its export), detection runs as for a new bank.

    Args:
        layout: a CSV layout the user is choosing. When given, the whole file is read with it,
            exactly as :func:`commit_import` would, so the preview shows what will be stored.

    Raises:
        ImportRequestError: if ``layout`` is given for a file that isn't CSV.
        StatementParseError: if the file can't be read as a statement at all, or a row doesn't
            fit ``layout`` (the message names the row).
    """
    previous = find_import(conn, file.sha256)
    statement_format = detect_format(file.data)
    if statement_format is StatementFormat.OFX:
        if layout is not None:
            raise ImportRequestError(_LAYOUT_FOR_NON_CSV)
        statement = parse_ofx(file.data)
        return ImportPreview(
            format=statement_format,
            file_name=file.name,
            rows=_preview_rows(statement.transactions),
            transaction_count=len(statement.transactions),
            currency=statement.currency,
            warnings=statement.warnings,
            previous_import=previous,
            csv=None,
        )

    detection = detect_csv(file.data)
    if layout is not None:
        return _csv_preview(
            file,
            previous,
            statement=parse_csv(file.data, layout),
            fallback_rows=(),
            csv=CsvPreview(
                layout=_draft_from_layout(layout),
                layout_source=LayoutSource.CHOSEN,
                columns=detection.columns,
                questions=(),
            ),
        )

    saved = _saved_layout(conn, detection.header_signature)
    if saved is not None:
        try:
            statement = parse_csv(file.data, saved)
        except StatementParseError as error:
            logger.info("Saved CSV layout no longer reads this file (%s); re-detecting", error)
        else:
            return _csv_preview(
                file,
                previous,
                statement=statement,
                fallback_rows=(),
                csv=CsvPreview(
                    layout=_draft_from_layout(saved),
                    layout_source=LayoutSource.SAVED,
                    columns=detection.columns,
                    questions=(),
                ),
            )

    statement = None
    layout = detection.layout.to_layout()
    if layout is not None:
        try:
            statement = parse_csv(file.data, layout)
        except StatementParseError:
            # Detection reports unreadable rows as a question; show its partial preview.
            statement = None
    return _csv_preview(
        file,
        previous,
        statement=statement,
        fallback_rows=detection.preview,
        csv=CsvPreview(
            layout=detection.layout,
            layout_source=LayoutSource.DETECTED,
            columns=detection.columns,
            questions=detection.questions,
        ),
    )


def commit_import(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    file: StatementFile,
    layout: CsvLayout | None,
) -> ImportOutcome:
    """Store every transaction in ``file`` in the account, skipping ones already stored.

    The import record, its transactions and (for CSV) the confirmed layout are saved together
    or not at all.

    Args:
        layout: the column layout the user confirmed. Required for CSV, refused for OFX.

    Raises:
        ImportRequestError: if a CSV has no layout, an OFX file has one, or the statement's
            currency differs from the account's.
        DuplicateImportError: if this exact file was imported before.
        NotFoundError: if the account does not exist.
        StatementParseError: if the file can't be read with the layout.
    """
    statement_format = detect_format(file.data)
    signature: str | None = None
    if statement_format is StatementFormat.CSV:
        if layout is None:
            raise ImportRequestError(
                "Confirm how the columns are laid out before importing this CSV file."
            )
        statement = parse_csv(file.data, layout)
        # Layouts are remembered per header row, so a file without one can't be recognised.
        signature = _header_signature(file.data) if layout.has_header else None
    else:
        if layout is not None:
            raise ImportRequestError(_LAYOUT_FOR_NON_CSV)
        statement = parse_ofx(file.data)

    account = get_account(conn, account_id)
    if statement.currency is not None and statement.currency != account.currency:
        raise ImportRequestError(
            f"This statement is in {statement.currency}, but {account.name} uses "
            f"{account.currency}. Choose an account in {statement.currency}."
        )

    items = [
        NewTransaction(raw=tx, merchant=normalize_merchant(tx.description))
        for tx in statement.transactions
    ]
    with atomic(conn):
        record = record_import(
            conn,
            account_id=account.id,
            file_name=file.name,
            file_sha256=file.sha256,
            statement_format=statement_format,
            row_count=len(items),
        )
        result = insert_transactions(conn, account_id=account.id, import_id=record.id, items=items)
        if layout is not None and signature is not None:
            save_csv_profile(conn, signature, json.dumps(layout.to_dict(), separators=(",", ":")))

    logger.info(
        "Imported %s: %d added, %d duplicates skipped",
        statement_format.value,
        result.added,
        result.skipped_duplicates,
    )
    return ImportOutcome(
        record=record,
        added=result.added,
        skipped_duplicates=result.skipped_duplicates,
        warnings=statement.warnings,
    )


def _csv_preview(
    file: StatementFile,
    previous: ImportRecord | None,
    *,
    statement: ParsedStatement | None,
    fallback_rows: tuple[RawTransaction, ...],
    csv: CsvPreview,
) -> ImportPreview:
    return ImportPreview(
        format=StatementFormat.CSV,
        file_name=file.name,
        rows=_preview_rows(fallback_rows if statement is None else statement.transactions),
        transaction_count=None if statement is None else len(statement.transactions),
        currency=None,
        warnings=() if statement is None else statement.warnings,
        previous_import=previous,
        csv=csv,
    )


def _preview_rows(transactions: tuple[RawTransaction, ...]) -> tuple[PreviewRow, ...]:
    return tuple(
        PreviewRow(transaction=tx, merchant=normalize_merchant(tx.description))
        for tx in transactions[:PREVIEW_ROWS]
    )


def _saved_layout(conn: sqlite3.Connection, signature: str | None) -> CsvLayout | None:
    if signature is None:
        return None
    mapping_json = get_csv_profile(conn, signature)
    if mapping_json is None:
        return None
    try:
        return CsvLayout.from_dict(json.loads(mapping_json))
    except (json.JSONDecodeError, CsvLayoutError) as error:
        # The database belongs to the user and can be edited; treat a bad profile as missing.
        logger.warning("Ignoring an unreadable saved CSV layout: %s", error)
        return None


def _header_signature(data: bytes) -> str | None:
    """The key the confirmed layout is saved under, or ``None`` for a file without a header."""
    try:
        return detect_csv(data).header_signature
    except StatementParseError:
        return None


def _draft_from_layout(layout: CsvLayout) -> CsvLayoutDraft:
    return CsvLayoutDraft(
        encoding=layout.encoding,
        delimiter=layout.delimiter,
        skip_rows=layout.skip_rows,
        has_header=layout.has_header,
        date_column=layout.date_column,
        description_column=layout.description_column,
        amount=layout.amount,
        date_format=layout.date_format,
        decimal_separator=layout.decimal_separator,
        invert_signs=layout.invert_signs,
    )
