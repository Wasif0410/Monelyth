from __future__ import annotations

import datetime

import pytest

from monelyth_engine.ingest.csv_values import (
    DATE_FORMATS,
    CsvValueError,
    DecimalSeparator,
    clean_description,
    date_format_label,
    has_credit_debit_marker,
    is_blank,
    match_date,
    parse_amount,
    parse_date,
    quote,
)

SEP_2026 = datetime.date(2026, 9, 5)


@pytest.mark.parametrize(
    ("text", "separator", "cents"),
    [
        ("12.99", ".", 1299),
        ("-12.99", ".", -1299),
        ("+5.00", ".", 500),
        ("12", ".", 1200),
        (".50", ".", 50),
        ("0.00", ".", 0),
        ("-0.00", ".", 0),
        ("12.990", ".", 1299),
        ("  7.25  ", ".", 725),
        ("$1,234.56", ".", 123456),
        ("1,234", ".", 123400),
        ("1,234,567.89", ".", 123456789),
        ("1'234.50", ".", 123450),
        ("-$12.99", ".", -1299),
        ("$-12.99", ".", -1299),
        ("12.99-", ".", -1299),
        ("(12.99)", ".", -1299),
        ("($1,234.00)", ".", -123400),
        ("12.99 CR", ".", 1299),
        ("12.99 DR", ".", -1299),
        ("12.99dr", ".", -1299),
        ("12.99 Cr.", ".", 1299),
        ("£7.10", ".", 710),
        ("CAD 12.00", ".", 1200),
        ("12.00 USD", ".", 1200),
        ("C$5", ".", 500),
        ("US$ 1,000", ".", 100000),
        ("\u221212.50", ".", -1250),
        ("1.234,56", ",", 123456),
        ("-45,67", ",", -4567),
        ("3.200,00", ",", 320000),
        ("1\u00a0250,00", ",", 125000),
        ("1 250,00", ",", 125000),
        ("12,50 €", ",", 1250),
        ("-€3,80", ",", -380),
        ("1.234", ",", 123400),
    ],
)
def test_parse_amount(text: str, separator: DecimalSeparator, cents: int) -> None:
    assert parse_amount(text, separator) == cents


@pytest.mark.parametrize("text", ["", "   ", "-", "\u2013", "\u2014", " - "])
def test_blank_amounts_are_none(text: str) -> None:
    assert is_blank(text)
    assert parse_amount(text, ".") is None


@pytest.mark.parametrize(
    ("text", "separator", "reason"),
    [
        ("abc", ".", "isn't a number"),
        ("12.3.4", ".", "isn't a number"),
        ("1,23.45", ".", "isn't a number"),
        ("12,50", ".", "isn't a number"),
        ("1.234,56", ".", "isn't a number"),
        ("1,234.56", ",", "isn't a number"),
        ("1,2345", ".", "isn't a number"),
        ("12.", ".", "isn't a number"),
        ("1e5", ".", "isn't a number"),
        ("NaN", ".", "isn't a number"),
        ("Infinity", ".", "isn't a number"),
        ("-(12.99)", ".", "isn't a number"),
        ("$12 $", ".", "isn't a number"),
        ("12 34", ".", "isn't a number"),
        ("1" * 100, ".", "isn't a number"),
        ("-12.99 CR", ".", "more than one sign"),
        ("(12.99) DR", ".", "more than one sign"),
        ("--5", ".", "more than one sign"),
        ("-5-", ".", "more than one sign"),
        ("12.999", ".", "fraction of a cent"),
        ("1.234", ".", "fraction of a cent"),
        ("0.001", ".", "fraction of a cent"),
        ("12345678901234.00", ".", "too large"),
    ],
)
def test_parse_amount_rejects(text: str, separator: DecimalSeparator, reason: str) -> None:
    with pytest.raises(CsvValueError, match=reason):
        parse_amount(text, separator)


def test_amount_error_quotes_the_cell() -> None:
    with pytest.raises(CsvValueError) as caught:
        parse_amount("twelve", ".")

    assert str(caught.value) == 'the amount "twelve" isn\'t a number'


def test_large_amount_within_limit_is_exact() -> None:
    assert parse_amount("9,999,999,999,999.99", ".") == 999_999_999_999_999


@pytest.mark.parametrize(
    ("text", "expected"),
    [("12.99 CR", True), ("12.99dr", True), ("12.99", False), ("CREDIT", False), ("", False)],
)
def test_credit_debit_marker(text: str, *, expected: bool) -> None:
    assert has_credit_debit_marker(text) is expected


@pytest.mark.parametrize(
    ("code", "text"),
    [
        ("%Y-%m-%d", "2026-09-05"),
        ("%Y/%m/%d", "2026/09/05"),
        ("%m/%d/%Y", "09/05/2026"),
        ("%m/%d/%Y", "9/5/2026"),
        ("%d/%m/%Y", "05/09/2026"),
        ("%m/%d/%y", "09/05/26"),
        ("%d/%m/%y", "05/09/26"),
        ("%m-%d-%Y", "09-05-2026"),
        ("%d-%m-%Y", "05-09-2026"),
        ("%d.%m.%Y", "05.09.2026"),
        ("%d.%m.%y", "05.09.26"),
        ("%d-%b-%Y", "05-Sep-2026"),
        ("%d-%b-%Y", "05-SEPT-2026"),
        ("%d-%b-%y", "05-sep-26"),
        ("%d %b %Y", "5 September 2026"),
        ("%b %d, %Y", "Sep 5, 2026"),
        ("%b %d, %Y", "Sep.  5, 2026"),
    ],
)
def test_match_date(code: str, text: str) -> None:
    assert match_date(text, code) == SEP_2026


@pytest.mark.parametrize(
    "text",
    ["2026-09-05 00:00:00", "2026-09-05T13:45", "2026-09-05 12:00 AM", " 2026-09-05 "],
)
def test_time_after_the_date_is_ignored(text: str) -> None:
    assert match_date(text, "%Y-%m-%d") == SEP_2026


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("2026-02-30", "%Y-%m-%d"),
        ("2026-13-01", "%Y-%m-%d"),
        ("13/05/2026", "%m/%d/%Y"),
        ("2026-09-05x", "%Y-%m-%d"),
        ("05-Sez-2026", "%d-%b-%Y"),
        ("26-09-05", "%Y-%m-%d"),
        ("\uff12\uff10\uff12\uff16-09-05", "%Y-%m-%d"),
        ("", "%Y-%m-%d"),
        ("2026-09-05 " + "9" * 100, "%Y-%m-%d"),
    ],
)
def test_match_date_rejects(text: str, code: str) -> None:
    assert match_date(text, code) is None


def test_two_digit_years_follow_the_posix_pivot() -> None:
    assert match_date("01/01/68", "%m/%d/%y") == datetime.date(2068, 1, 1)
    assert match_date("01/01/69", "%m/%d/%y") == datetime.date(1969, 1, 1)


def test_parse_date_error_names_the_format() -> None:
    with pytest.raises(CsvValueError) as caught:
        parse_date("31/31/2026", "%d/%m/%Y")

    assert str(caught.value) == 'the date "31/31/2026" doesn\'t match the format DD/MM/YYYY'


def test_every_date_format_has_a_label() -> None:
    assert date_format_label("%b %d, %Y") == "Mon DD, YYYY"
    assert date_format_label("%d.%m.%y") == "DD.MM.YY"
    assert all(date_format_label(code) for code in DATE_FORMATS)


def test_clean_description_collapses_whitespace() -> None:
    assert clean_description("  SQ *BLUE \t BOTTLE\n\u00a0COFFEE  ") == "SQ *BLUE BOTTLE COFFEE"
    assert clean_description(" \t ") == ""


def test_quote_shortens_long_text() -> None:
    assert quote("Coffee") == '"Coffee"'
    assert quote("x" * 100) == '"' + "x" * 39 + '…"'
