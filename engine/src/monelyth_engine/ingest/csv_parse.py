"""Read every row of a CSV statement with a layout the user has confirmed."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from monelyth_engine.ingest.csv_layout import CsvLayout, DebitCredit, SignedAmount
from monelyth_engine.ingest.csv_reader import cell_at, decode, iter_rows
from monelyth_engine.ingest.csv_values import (
    CsvValueError,
    clean_description,
    is_blank,
    parse_amount,
    parse_date,
    quote,
)
from monelyth_engine.ingest.models import (
    ParsedStatement,
    RawTransaction,
    StatementFormat,
    StatementParseError,
)

MAX_ROW_WARNINGS: Final = 20
"""Skipped rows named one by one in the warnings; the rest are counted in one line."""

# Lines such as "Total", "Closing balance" or "Balance forward" that summarise the statement.
_SUMMARY_LABEL: Final = re.compile(
    r"(?:sub ?)?totals?\b"
    r"|(?:opening|closing|beginning|ending|starting|previous|new|final) balance\b"
    r"|balance (?:forward|brought forward|carried forward)\b"
    r"|(?:anfangs|end|schluss)?saldo\b|summe\b"
)


class SkipReason(Enum):
    BLANK = auto()
    REPEATED_HEADER = auto()
    SINGLE_VALUE = auto()
    SUMMARY = auto()


@dataclass(frozen=True, slots=True)
class SkippedRow:
    """A row that holds no transaction, kept so the user can be told what was left out."""

    row_number: int
    reason: SkipReason
    text: str = ""
    """The cell that shows why, e.g. ``"Closing balance"``."""


def parse_csv(data: bytes, layout: CsvLayout) -> ParsedStatement:
    """Read every transaction in a CSV statement.

    Blank rows, single-value notes, repeated headers and summary lines ("Total", "Closing
    balance") are skipped and listed in :attr:`ParsedStatement.warnings`. Any other row that
    can't be read stops the import, because silently dropping a transaction would make every
    total wrong.

    Raises:
        StatementParseError: if the file breaks a size limit, doesn't match the layout, has a
            row that can't be read (the message names the row), or has no transactions.
    """
    transactions: list[RawTransaction] = []
    named_skips: list[SkippedRow] = []
    unnamed_skips = 0
    blank_rows = 0
    for outcome in iter_transactions(decode(data, layout.encoding), layout):
        if isinstance(outcome, RawTransaction):
            transactions.append(outcome)
        elif outcome.reason is SkipReason.BLANK:
            blank_rows += 1
        elif len(named_skips) < MAX_ROW_WARNINGS:
            named_skips.append(outcome)
        else:
            unnamed_skips += 1

    if not transactions:
        raise StatementParseError(
            "No transactions were found in the file. Check that the right rows and columns "
            "are chosen."
        )

    warnings = [_describe_skip(skip) for skip in named_skips]
    if unnamed_skips:
        warnings.append(f"Skipped {_rows(unnamed_skips, 'more')} that weren't transactions.")
    if blank_rows:
        warnings.append(f"Skipped {_rows(blank_rows, 'blank')}.")
    return ParsedStatement(StatementFormat.CSV, tuple(transactions), warnings=tuple(warnings))


def iter_transactions(text: str, layout: CsvLayout) -> Iterator[RawTransaction | SkippedRow]:
    """Yield each data row of decoded ``text`` as a transaction or as the reason it was skipped.

    Detection uses this too, to preview a guessed layout and to check it against every row.
    """
    # Row numbers count from 1, while skip_rows counts the rows above the header.
    header_row = layout.skip_rows + 1 if layout.has_header else None
    first_data_row = layout.skip_rows + (2 if layout.has_header else 1)
    header_key: tuple[str, ...] | None = None
    last_row = 0
    for row_number, cells in iter_rows(text, layout.delimiter):
        last_row = row_number
        if row_number == header_row:
            header_key = _check_header(cells, layout)
        elif row_number >= first_data_row:
            yield _read_row(row_number, cells, layout, header_key)

    if header_row is not None and last_row < header_row:
        raise StatementParseError(
            f"The file has only {_rows(last_row)}, but the layout expects the header on row "
            f"{header_row}."
        )


def normalize_header(cells: Sequence[str]) -> tuple[str, ...]:
    """Header cells compared without regard to case or spacing."""
    return tuple(clean_description(cell).casefold() for cell in cells)


def repeats_header(cells: Sequence[str], header_key: tuple[str, ...]) -> bool:
    """Whether a row is the header again, as some banks print it at the top of every page."""
    return (
        len(cells) == len(header_key)
        and clean_description(cells[0]).casefold() == header_key[0]
        and normalize_header(cells) == header_key
    )


def is_summary_label(text: str) -> bool:
    """Whether a cell reads like a statement summary line rather than a transaction."""
    if not text.lstrip()[:1].isalpha():
        return False  # Fast path for the numbers and dates that fill most cells.
    return _SUMMARY_LABEL.match(clean_description(text).casefold()) is not None


def _check_header(cells: list[str], layout: CsvLayout) -> tuple[str, ...]:
    widest = max(layout.columns)
    if widest >= len(cells):
        raise StatementParseError(
            f"The layout reads column {widest + 1}, but the header row has only "
            f"{len(cells)} columns. Check that the right header row is chosen."
        )
    return normalize_header(cells)


def _read_row(
    row_number: int, cells: list[str], layout: CsvLayout, header_key: tuple[str, ...] | None
) -> RawTransaction | SkippedRow:
    values = [cell for cell in cells if not is_blank(cell)]
    if not values:
        return SkippedRow(row_number, SkipReason.BLANK)
    if header_key is not None and repeats_header(cells, header_key):
        return SkippedRow(row_number, SkipReason.REPEATED_HEADER)
    if len(values) == 1:
        return SkippedRow(row_number, SkipReason.SINGLE_VALUE, values[0])

    date_text = cell_at(cells, layout.date_column)
    amount_texts = [cell_at(cells, column) for column in layout.amount.columns]
    # A summary line is skipped only when it also lacks a date or an amount, so a real
    # purchase at a merchant such as "TOTAL" (a fuel chain) is still imported.
    lacks_date = is_blank(date_text) or is_summary_label(date_text)
    if lacks_date or all(is_blank(text) for text in amount_texts):
        label = next((value for value in values if is_summary_label(value)), None)
        if label is not None:
            return SkippedRow(row_number, SkipReason.SUMMARY, label)

    try:
        return _transaction(cells, layout, date_text, amount_texts)
    except CsvValueError as error:
        raise StatementParseError(f"Row {row_number}: {error}.") from error


def _transaction(
    cells: list[str], layout: CsvLayout, date_text: str, amount_texts: list[str]
) -> RawTransaction:
    if is_blank(date_text):
        raise CsvValueError("there's no date")
    posted_date = parse_date(date_text, layout.date_format)

    description = clean_description(cell_at(cells, layout.description_column))
    if not description:
        raise CsvValueError("there's no description")

    separator = layout.decimal_separator
    match layout.amount:
        case SignedAmount():
            amount = parse_amount(amount_texts[0], separator)
            if amount is None:
                raise CsvValueError("there's no amount")
        case DebitCredit():
            debit, credit = (parse_amount(text, separator) for text in amount_texts)
            if debit is None and credit is None:
                raise CsvValueError("there's no amount in the debit or credit column")
            amount = abs(credit or 0) - abs(debit or 0)

    return RawTransaction(posted_date, -amount if layout.invert_signs else amount, description)


def _rows(count: int, kind: str = "") -> str:
    """``"1 row"``, ``"3 rows"``, or with a ``kind``, ``"3 blank rows"``."""
    noun = "row" if count == 1 else "rows"
    return f"{count:,} {kind} {noun}" if kind else f"{count:,} {noun}"


def _describe_skip(skip: SkippedRow) -> str:
    match skip.reason:
        case SkipReason.REPEATED_HEADER:
            return f"Skipped row {skip.row_number} because it repeats the header."
        case SkipReason.SINGLE_VALUE:
            return (
                f"Skipped row {skip.row_number} because it holds only {quote(skip.text)}, "
                "not a transaction."
            )
        case SkipReason.SUMMARY:
            return (
                f"Skipped row {skip.row_number} because it looks like a summary line "
                f"({quote(skip.text)}), not a transaction."
            )
        case SkipReason.BLANK:
            return f"Skipped row {skip.row_number} because it is blank."
