from __future__ import annotations

import dataclasses
import datetime
import re

import pytest

from monelyth_engine.ingest.csv_layout import CsvLayout, DebitCredit, SignedAmount
from monelyth_engine.ingest.csv_parse import MAX_ROW_WARNINGS, parse_csv
from monelyth_engine.ingest.csv_reader import MAX_FILE_BYTES, MAX_ROWS
from monelyth_engine.ingest.models import ParsedStatement, RawTransaction, StatementParseError

SIGNED = CsvLayout(
    encoding="utf-8-sig",
    delimiter=",",
    skip_rows=0,
    has_header=True,
    date_column=0,
    description_column=1,
    amount=SignedAmount(2),
    date_format="%Y-%m-%d",
    decimal_separator=".",
    invert_signs=False,
)
DEBIT_CREDIT = dataclasses.replace(SIGNED, amount=DebitCredit(debit_column=2, credit_column=3))


def _parse(*lines: str, layout: CsvLayout = SIGNED) -> ParsedStatement:
    return parse_csv(("\n".join(lines) + "\n").encode(), layout)


def _amounts(statement: ParsedStatement) -> list[int]:
    return [transaction.amount_cents for transaction in statement.transactions]


def _fails(message: str, *lines: str, layout: CsvLayout = SIGNED) -> None:
    with pytest.raises(StatementParseError, match=f"^{re.escape(message)}$"):
        _parse(*lines, layout=layout)


def test_debit_and_credit_columns() -> None:
    statement = _parse(
        "Date,Description,Debit,Credit",
        "2026-09-01,Coffee,4.50,",
        "2026-09-02,Refund,,3.00",
        "2026-09-03,Signed debit,-12.00,",
        "2026-09-04,Both filled,10.00,25.00",
        "2026-09-05,Zero,0.00,",
        layout=DEBIT_CREDIT,
    )

    assert _amounts(statement) == [-450, 300, -1200, 1500, 0]


def test_invert_signs_flips_card_statements() -> None:
    layout = dataclasses.replace(SIGNED, invert_signs=True)

    statement = _parse(
        "Date,Description,Amount",
        "2026-09-01,Purchase,4.50",
        "2026-09-02,Payment,-100",
        layout=layout,
    )

    assert _amounts(statement) == [-450, 10000]


def test_quoted_line_breaks_count_as_one_row() -> None:
    lines = ("Date,Description,Amount", '2026-09-01,"Two\nlines",-1.00', "2026-09-02,Bad,abc")

    with pytest.raises(StatementParseError, match=r'^Row 3: the amount "abc"'):
        _parse(*lines)
    assert _parse(*lines[:2]).transactions[0].description == "Two lines"


def test_full_transaction_values() -> None:
    statement = _parse("Date,Description,Amount", "2026-09-01 00:00:00,  SQ  *CAFE ,(4.50)")

    assert statement.transactions == (RawTransaction(datetime.date(2026, 9, 1), -450, "SQ *CAFE"),)
    assert statement.warnings == ()


def test_short_rows_are_read_as_far_as_they_go() -> None:
    _fails("Row 2: there's no amount.", "Date,Description,Amount", "2026-09-01,Coffee")


def test_extra_cells_are_ignored() -> None:
    statement = _parse("Date,Description,Amount", "2026-09-01,Coffee,-4.50,extra,cells")

    assert _amounts(statement) == [-450]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (",Coffee,-4.50", "Row 3: there's no date."),
        (
            "01/09/2026,Coffee,-4.50",
            'Row 3: the date "01/09/2026" doesn\'t match the format YYYY-MM-DD.',
        ),
        (
            "2026-02-30,Coffee,-4.50",
            'Row 3: the date "2026-02-30" doesn\'t match the format YYYY-MM-DD.',
        ),
        ("2026-09-01,,-4.50", "Row 3: there's no description."),
        ("2026-09-01,  ,-4.50", "Row 3: there's no description."),
        ("2026-09-01,Coffee,", "Row 3: there's no amount."),
        ("2026-09-01,Coffee,4.5O", 'Row 3: the amount "4.5O" isn\'t a number.'),
        ("2026-09-01,Coffee,1.999", 'Row 3: the amount "1.999" has a fraction of a cent.'),
    ],
)
def test_bad_rows_name_the_row_and_the_reason(row: str, message: str) -> None:
    _fails(message, "Date,Description,Amount", "2026-09-01,Fine,-1.00", row)


def test_debit_and_credit_both_blank_is_an_error() -> None:
    _fails(
        "Row 2: there's no amount in the debit or credit column.",
        "Date,Description,Debit,Credit",
        "2026-09-01,Coffee,,",
        layout=DEBIT_CREDIT,
    )


def test_skipped_rows_are_reported() -> None:
    statement = _parse(
        "Date,Description,Amount",
        "2026-09-01,Coffee,-4.50",
        "",
        ",,",
        "Date,Description,Amount",
        "End of statement",
        "2026-09-02,Closing balance,",
        "Total,,-4.50",
        ",Total debits,-4.50",
    )

    assert _amounts(statement) == [-450]
    assert statement.warnings == (
        "Skipped row 5 because it repeats the header.",
        'Skipped row 6 because it holds only "End of statement", not a transaction.',
        'Skipped row 7 because it looks like a summary line ("Closing balance"), not a '
        "transaction.",
        'Skipped row 8 because it looks like a summary line ("Total"), not a transaction.',
        'Skipped row 9 because it looks like a summary line ("Total debits"), not a transaction.',
        "Skipped 2 blank rows.",
    )


def test_merchants_named_like_summaries_are_still_imported() -> None:
    statement = _parse(
        "Date,Description,Amount", "2026-09-01,TOTAL WINE & MORE,-30.00", "2026-09-02,TOTAL,-50.00"
    )

    assert [t.description for t in statement.transactions] == ["TOTAL WINE & MORE", "TOTAL"]


def test_summary_label_with_a_bad_date_is_still_an_error() -> None:
    _fails(
        'Row 2: the date "2026-99-01" doesn\'t match the format YYYY-MM-DD.',
        "Date,Description,Amount",
        "2026-99-01,Total Wine,-30.00",
    )


def test_many_skipped_rows_are_summarised() -> None:
    notes = [f"Note {number}" for number in range(MAX_ROW_WARNINGS + 5)]

    statement = _parse("Date,Description,Amount", "2026-09-01,Coffee,-4.50", *notes)

    assert len(statement.warnings) == MAX_ROW_WARNINGS + 1
    assert statement.warnings[-1] == "Skipped 5 more rows that weren't transactions."


def test_skip_rows_and_no_header() -> None:
    layout = dataclasses.replace(SIGNED, skip_rows=2, has_header=False)

    statement = _parse("Bank of Nowhere", "Account 1234", "2026-09-01,Coffee,-4.50", layout=layout)

    assert _amounts(statement) == [-450]


def test_header_missing_where_the_layout_expects_it() -> None:
    _fails(
        "The file has only 2 rows, but the layout expects the header on row 6.",
        "Bank of Nowhere",
        "Account 1234",
        layout=dataclasses.replace(SIGNED, skip_rows=5),
    )


def test_layout_columns_beyond_the_header() -> None:
    _fails(
        "The layout reads column 6, but the header row has only 3 columns. Check that the "
        "right header row is chosen.",
        "Date,Description,Amount",
        "2026-09-01,Coffee,-4.50",
        layout=dataclasses.replace(SIGNED, amount=SignedAmount(5)),
    )


def test_no_transactions() -> None:
    _fails(
        "No transactions were found in the file. Check that the right rows and columns are chosen.",
        "Date,Description,Amount",
        "",
        "Total,,0.00",
    )


def test_encoding_must_match_the_layout() -> None:
    data = "Date,Description,Amount\n2026-09-01,Café,-4.50\n".encode("cp1252")

    with pytest.raises(StatementParseError, match="isn't valid UTF-8 text"):
        parse_csv(data, SIGNED)
    cafe = parse_csv(data, dataclasses.replace(SIGNED, encoding="cp1252")).transactions[0]
    assert cafe.description == "Café"


def test_delimiter_comes_from_the_layout() -> None:
    layout = dataclasses.replace(SIGNED, delimiter=";", decimal_separator=",")

    statement = _parse("Date;Description;Amount", "2026-09-01;Café, Bar;-4,50", layout=layout)

    assert statement.transactions[0] == RawTransaction(datetime.date(2026, 9, 1), -450, "Café, Bar")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "The file is empty."),
        (b"%PDF-1.4", "This is a PDF"),
        (b"a,b\x00", "isn't a text file"),
        (b"a" * (MAX_FILE_BYTES + 1), "the most Monelyth reads is 20 MB"),
        (b"Date,Description,Amount\n" + b"\n" * MAX_ROWS, "more than 100,000 rows"),
        (b"Date,Description,Amount\n" + b";" * 70 + b",x" * 70, "Row 2 has 71 columns"),
    ],
    ids=["empty", "pdf", "binary", "too-large", "too-many-rows", "too-many-columns"],
)
def test_limits_apply_to_parsing_too(data: bytes, message: str) -> None:
    with pytest.raises(StatementParseError, match=message):
        parse_csv(data, SIGNED)


def test_large_valid_file_parses() -> None:
    rows = "".join(f"2026-09-{day % 28 + 1:02d},Shop {day},-{day}.25\n" for day in range(20_000))

    statement = parse_csv(f"Date,Description,Amount\n{rows}".encode(), SIGNED)

    assert len(statement.transactions) == 20_000
    assert statement.transactions[-1].amount_cents == -1_999_925
