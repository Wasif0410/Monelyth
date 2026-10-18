"""Importing statement files: preview first, then commit.

Both routes take the file as multipart form data. The UI uploads the same file twice (once to
preview, once to import) rather than the engine keeping uploads between requests, so an
abandoned preview leaves nothing behind.
"""

from __future__ import annotations

import datetime
import json
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Form, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from monelyth_engine.api.deps import Connection
from monelyth_engine.ingest.csv_statement import (
    DATE_FORMATS,
    CsvLayout,
    CsvQuestionKind,
    DecimalSeparator,
    Delimiter,
    Encoding,
    date_format_label,
)
from monelyth_engine.ingest.models import StatementFormat
from monelyth_engine.services.importing import (
    MAX_UPLOAD_BYTES,
    ImportOutcome,
    ImportPreview,
    ImportRequestError,
    LayoutSource,
    StatementFile,
    commit_import,
    preview_import,
)

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_LAYOUT_JSON_LENGTH = 10_000
"""A saved layout is a few hundred characters; anything far larger is not one."""


class PreviewRowOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    posted_date: datetime.date
    description: str
    merchant: str
    amount_cents: int


class CsvQuestionOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: CsvQuestionKind
    message: str
    options: list[str]


class SignedAmountOut(BaseModel):
    """One column holds every amount, negative for money out (unless ``invert_signs``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["signed"]
    column: int


class DebitCreditOut(BaseModel):
    """Money out and money in sit in separate columns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["debit_credit"]
    debit_column: int
    credit_column: int


class CsvLayoutOut(BaseModel):
    """A CSV layout in exactly the shape ``POST /imports`` takes as ``layout``, except that
    ``null`` marks a part the user still has to choose. Columns count from 0."""

    # extra="forbid": if the saved layout gains a field, this model must gain it too.
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    encoding: Encoding
    delimiter: Delimiter
    skip_rows: int
    has_header: bool
    date_column: int | None
    description_column: int | None
    amount: Annotated[SignedAmountOut | DebitCreditOut, Field(discriminator="kind")] | None
    date_format: str | None
    """One of the codes in ``CsvPreviewOut.date_formats``."""
    decimal_separator: DecimalSeparator
    invert_signs: bool | None
    """``true`` when the statement shows purchases as positive numbers."""


class DateFormatOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    """The value for ``layout.date_format``."""
    label: str
    """How the format is shown to people, e.g. ``DD/MM/YYYY``."""


_DATE_FORMATS: Final = tuple(
    DateFormatOut(code=code, label=date_format_label(code)) for code in DATE_FORMATS
)


class CsvPreviewOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    layout: CsvLayoutOut
    layout_source: LayoutSource
    columns: list[str]
    """Column names from the header row, or generated ones ("Column 1") without a header."""
    questions: list[CsvQuestionOut]
    date_formats: list[DateFormatOut]
    """Every date format a layout may use, in the order detection prefers them."""


class PreviousImportOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    account_id: int
    file_name: str
    imported_at: datetime.datetime


class ImportPreviewOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    format: StatementFormat
    file_name: str
    rows: list[PreviewRowOut]
    transaction_count: int | None
    currency: str | None
    warnings: list[str]
    previous_import: PreviousImportOut | None
    """Set when this exact file was imported before; importing it again will be refused."""
    csv: CsvPreviewOut | None

    @classmethod
    def of(cls, preview: ImportPreview) -> ImportPreviewOut:
        previous = preview.previous_import
        csv = preview.csv
        return cls(
            format=preview.format,
            file_name=preview.file_name,
            rows=[
                PreviewRowOut(
                    posted_date=row.transaction.posted_date,
                    description=row.transaction.description,
                    merchant=row.merchant,
                    amount_cents=row.transaction.amount_cents,
                )
                for row in preview.rows
            ],
            transaction_count=preview.transaction_count,
            currency=preview.currency,
            warnings=list(preview.warnings),
            previous_import=None
            if previous is None
            else PreviousImportOut(
                id=previous.id,
                account_id=previous.account_id,
                file_name=previous.file_name,
                imported_at=previous.imported_at,
            ),
            csv=None
            if csv is None
            else CsvPreviewOut(
                # Built from to_dict(), the form POST /imports reads back, so the two can't drift.
                layout=CsvLayoutOut.model_validate(csv.layout.to_dict()),
                layout_source=csv.layout_source,
                columns=list(csv.columns),
                questions=[
                    CsvQuestionOut(kind=q.kind, message=q.message, options=list(q.options))
                    for q in csv.questions
                ],
                date_formats=list(_DATE_FORMATS),
            ),
        )


class ImportResultOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    import_id: int
    account_id: int
    file_name: str
    format: StatementFormat
    added: int
    skipped_duplicates: int
    """Transactions already stored from an earlier, overlapping statement."""
    warnings: list[str]

    @classmethod
    def of(cls, outcome: ImportOutcome) -> ImportResultOut:
        record = outcome.record
        return cls(
            import_id=record.id,
            account_id=record.account_id,
            file_name=record.file_name,
            format=record.format,
            added=outcome.added,
            skipped_duplicates=outcome.skipped_duplicates,
            warnings=list(outcome.warnings),
        )


@router.post("/preview")
def post_import_preview(
    file: UploadFile,
    conn: Connection,
    layout: Annotated[
        str | None,
        Form(
            max_length=MAX_LAYOUT_JSON_LENGTH,
            description="A column layout to read the whole file with, as JSON in the shape "
            "POST /imports takes. CSV only. Without it, the engine detects the layout.",
        ),
    ] = None,
) -> ImportPreviewOut:
    """Read a statement without saving anything, and say what the user still has to confirm.

    With ``layout``, every row is read with it, so the rows and count match what importing would
    store, and a row that doesn't fit is reported as an error naming the row.
    """
    preview = preview_import(
        conn, _read_upload(file), layout=None if layout is None else _parse_layout(layout)
    )
    return ImportPreviewOut.of(preview)


@router.post("", status_code=status.HTTP_201_CREATED)
def post_import(
    file: UploadFile,
    account_id: Annotated[int, Form(ge=1)],
    conn: Connection,
    layout: Annotated[
        str | None,
        Form(
            max_length=MAX_LAYOUT_JSON_LENGTH,
            description="Confirmed column layout as JSON. Required for CSV, refused for OFX.",
        ),
    ] = None,
) -> ImportResultOut:
    """Store a statement's transactions in an account, skipping ones already stored."""
    outcome = commit_import(
        conn,
        account_id=account_id,
        file=_read_upload(file),
        layout=None if layout is None else _parse_layout(layout),
    )
    return ImportResultOut.of(outcome)


def _read_upload(file: UploadFile) -> StatementFile:
    # Read one byte past the limit so an oversized file is detected without reading all of it.
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    return StatementFile.from_upload(file.filename, data)


def _parse_layout(layout_json: str) -> CsvLayout:
    try:
        data: object = json.loads(layout_json)
    except json.JSONDecodeError:
        raise ImportRequestError(
            "The column layout sent with the file is not valid JSON."
        ) from None
    return CsvLayout.from_dict(data)
