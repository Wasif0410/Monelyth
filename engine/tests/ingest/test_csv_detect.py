from __future__ import annotations

import pytest

from monelyth_engine.ingest.csv_detect import (
    PREVIEW_ROWS,
    CsvDetection,
    CsvQuestion,
    CsvQuestionKind,
    detect_csv,
    header_signature,
)
from monelyth_engine.ingest.csv_layout import DebitCredit, SignedAmount
from monelyth_engine.ingest.csv_reader import MAX_FILE_BYTES, MAX_ROWS
from monelyth_engine.ingest.models import StatementParseError


def _detect(*lines: str) -> CsvDetection:
    return detect_csv(("\n".join(lines) + "\n").encode())


def _question(detection: CsvDetection, kind: CsvQuestionKind) -> CsvQuestion:
    matches = [question for question in detection.questions if question.kind is kind]
    assert len(matches) == 1, detection.questions
    return matches[0]


def _kinds(detection: CsvDetection) -> list[CsvQuestionKind]:
    return [question.kind for question in detection.questions]


def test_ambiguous_dates_ask_for_the_order() -> None:
    detection = _detect(
        "Date,Description,Amount",
        "01/02/2026,Coffee,-4.50",
        "05/02/2026,Groceries,-60.00",
        "03/03/2026,Salary,2000.00",
    )

    question = _question(detection, CsvQuestionKind.DATE_ORDER_AMBIGUOUS)
    assert detection.layout.date_format is None
    assert detection.preview == ()
    # Read day first the dates rise steadily (Feb 1, Feb 5, Mar 3); month first they don't
    # (Jan 2, May 2, Mar 3), so day first is offered first.
    assert question.options == ("%d/%m/%Y", "%m/%d/%Y")
    assert question.message == (
        'Dates such as "01/02/2026" could be read as DD/MM/YYYY or MM/DD/YYYY. '
        "Which does your bank use?"
    )


def test_dates_that_read_the_same_either_way_need_no_question() -> None:
    detection = _detect("Date,Description,Amount", "01/01/2026,A,-1.00", "02/02/2026,B,-2.00")

    assert detection.questions == ()
    assert detection.layout.date_format == "%m/%d/%Y"


def test_one_unambiguous_date_settles_the_order() -> None:
    detection = _detect("Date,Description,Amount", "01/02/2026,A,-1.00", "01/13/2026,B,-2.00")

    assert detection.layout.date_format == "%m/%d/%Y"
    assert detection.questions == ()


def test_unreadable_dates_are_a_question() -> None:
    detection = _detect("Date,Description,Amount", "yesterday,Coffee,-4.50", "today,Tea,-3.00")

    question = _question(detection, CsvQuestionKind.DATE_FORMAT_UNKNOWN)
    assert detection.layout.date_column == 0
    assert detection.layout.date_format is None
    assert '"yesterday"' in question.message


def test_dates_in_mixed_formats_are_a_question() -> None:
    detection = _detect("Date,Description,Amount", "2026-09-01,Coffee,-4.50", "09/02/2026,Tea,-3")

    question = _question(detection, CsvQuestionKind.DATE_FORMAT_UNKNOWN)
    assert "aren't all written the same way" in question.message


def test_every_row_is_checked_not_just_the_sample() -> None:
    rows = [f"2026-09-{day % 28 + 1:02d},Coffee {day},-4.50" for day in range(700)]
    rows[650] = "2026-13-01,Broken,-1.00"

    detection = _detect("Date,Description,Amount", *rows)

    question = _question(detection, CsvQuestionKind.DATE_FORMAT_UNKNOWN)
    assert '"2026-13-01"' in question.message


def test_missing_amount_column() -> None:
    detection = _detect("Date,Description,Reference", "2026-09-01,Coffee,ABC", "2026-09-02,Tea,DEF")

    assert detection.layout.amount is None
    assert _kinds(detection) == [CsvQuestionKind.NO_AMOUNT_COLUMN]
    assert detection.preview == ()


@pytest.mark.parametrize(
    ("name", "missing"), [("Withdrawals", "money in"), ("Deposits", "money out")]
)
def test_only_one_of_debit_and_credit(name: str, missing: str) -> None:
    detection = _detect(f"Date,Description,{name}", "2026-09-01,Coffee,4.50")

    question = _question(detection, CsvQuestionKind.NO_AMOUNT_COLUMN)
    assert f"Choose the column for {missing}" in question.message


def test_missing_date_column() -> None:
    detection = _detect("Description,Amount", "Coffee,-4.50", "Tea,-3.00")

    assert _kinds(detection) == [CsvQuestionKind.NO_DATE_COLUMN]
    assert detection.layout.date_column is None


def test_missing_description_column() -> None:
    detection = _detect("Date,Amount", "2026-09-01,-4.50", "2026-09-02,-3.00")

    assert _kinds(detection) == [CsvQuestionKind.NO_DESCRIPTION_COLUMN]


def test_unreadable_amounts_are_a_question() -> None:
    detection = _detect("Date,Description,Amount", "2026-09-01,Coffee,four", "2026-09-02,Tea,-3")

    question = _question(detection, CsvQuestionKind.AMOUNT_FORMAT_UNKNOWN)
    assert detection.layout.amount is None
    assert '"four"' in question.message
    assert CsvQuestionKind.NO_AMOUNT_COLUMN not in _kinds(detection)


def test_all_positive_amounts_ask_about_the_sign() -> None:
    detection = _detect("Date,Description,Amount", "2026-09-01,Coffee,4.50", "2026-09-02,Tea,3")

    question = _question(detection, CsvQuestionKind.SIGN_CONVENTION_UNKNOWN)
    assert detection.layout.invert_signs is None
    assert question.message.startswith("Every amount in this file is positive")


def test_mostly_negative_amounts_are_bank_style() -> None:
    detection = _detect(
        "Date,Description,Amount",
        "2026-09-01,Coffee,-4.50",
        "2026-09-02,Refund,3.00",
        "2026-09-03,Lunch,-12.00",
    )

    assert detection.layout.invert_signs is False
    assert detection.questions == ()


def test_unfamiliar_header_names_are_kept_and_columns_guessed() -> None:
    detection = _detect("When,What,How much", "2026-09-01,Coffee,-4.50", "2026-09-02,Tea,-3.00")

    assert detection.layout.has_header is True
    assert detection.columns == ("When", "What", "How much")
    assert detection.header_signature is not None
    assert (detection.layout.date_column, detection.layout.description_column) == (0, 1)
    assert detection.layout.amount == SignedAmount(2)
    assert _question(detection, CsvQuestionKind.COLUMNS_GUESSED).message == (
        "The header doesn't name the date, amount and description columns, so Monelyth guessed "
        "them from the data. Check that they're right."
    )


def test_one_unnamed_column_is_guessed_alone() -> None:
    detection = _detect("Date,Description,Value", "2026-09-01,Coffee,-4.50", "2026-09-02,Tea,-3")

    assert detection.layout.amount == SignedAmount(2)
    assert "doesn't name the amount column" in detection.questions[0].message


def test_headerless_file_guesses_a_signed_amount_and_text_description() -> None:
    # The layout Wells Fargo-style exports use: date, amount, "*", blank, description.
    detection = _detect(
        '"09/02/2026","-4.50","*","","SQ *CORNER CAFE"',
        '"09/15/2026","1500.00","*","","PAYROLL"',
    )

    assert detection.layout.has_header is False
    assert detection.layout.amount == SignedAmount(1)
    assert detection.layout.description_column == 4
    assert detection.header_signature is None
    assert _kinds(detection) == [CsvQuestionKind.COLUMNS_GUESSED]


def test_header_prefers_the_posting_date_and_the_main_description() -> None:
    detection = _detect(
        "Transaction Date,Posted Date,Memo,Payee,Debit Amount,Credit Amount,Running Balance",
        "09/01/2026,09/02/2026,POS 1234,Corner Cafe,4.50,,100.00",
        "09/14/2026,09/15/2026,DEP,Employer,,500.00,600.00",
    )

    assert detection.layout.date_column == 1
    assert detection.layout.description_column == 3
    assert detection.layout.amount == DebitCredit(4, 5)


def test_header_names_match_without_case_accents_or_currency() -> None:
    detection = _detect("  TRANSACTION   DATE ,MERCHANT NAME,Amount (CAD)", "2026-09-01,Cafe,-4.50")

    assert detection.layout.date_column == 0
    assert detection.layout.description_column == 1
    assert detection.layout.amount == SignedAmount(2)


def test_balance_column_is_never_the_amount() -> None:
    detection = _detect("Date,Description,Balance", "2026-09-01,Coffee,95.50")

    assert detection.layout.amount is None
    assert CsvQuestionKind.NO_AMOUNT_COLUMN in _kinds(detection)


def test_complete_layout_with_a_bad_row_is_a_question() -> None:
    detection = _detect("Date,Description,Amount", "2026-09-01,Coffee,-4.50", "2026-09-02,,-3.00")

    question = _question(detection, CsvQuestionKind.ROW_UNREADABLE)
    assert question.message == "Row 3: there's no description."
    assert len(detection.preview) == 1


def test_preview_is_limited() -> None:
    rows = [f"2026-09-{day:02d},Coffee {day},-4.50" for day in range(1, 26)]

    detection = _detect("Date,Description,Amount", *rows)

    assert len(detection.preview) == PREVIEW_ROWS
    assert detection.preview[-1].description == "Coffee 10"


def test_header_signature_ignores_case_and_spacing_only() -> None:
    base = header_signature(["Date", "Description", "Amount"])

    assert header_signature([" date ", "DESCRIPTION", "Amount"]) == base
    assert header_signature(["Date", "Details", "Amount"]) != base
    assert header_signature(["Description", "Date", "Amount"]) != base
    assert header_signature(["Date", "Description", "Amount", ""]) != base
    assert header_signature(["Date", "Description,Amount"]) != base


def test_same_bank_gets_the_same_signature_for_different_months() -> None:
    september = _detect("Account,1234", "Date,Description,Amount", "2026-09-01,Coffee,-4.50")
    october = _detect(
        "Account,1234", "Period,October", "DATE,Description,Amount", "2026-10-01,Tea,-3.00"
    )

    assert september.header_signature == october.header_signature
    assert (september.layout.skip_rows, october.layout.skip_rows) == (1, 2)


def test_semicolon_wins_over_decimal_commas() -> None:
    detection = _detect("Datum;Text;Betrag", "01.09.2026;Kaffee;-4,50", "02.09.2026;Tee;-3,20")

    assert detection.layout.delimiter == ";"
    assert detection.layout.decimal_separator == ","
    assert detection.preview[0].amount_cents == -450


def test_preamble_without_header_is_skipped() -> None:
    detection = _detect(
        "Statement for account 1234",
        "Generated 2026-10-01",
        "2026-09-01,Coffee,-4.50,100.00",
        "2026-09-02,Tea,-3.00,97.00",
    )

    assert detection.layout.has_header is False
    assert detection.layout.skip_rows == 2
    assert len(detection.preview) == 2


def test_summary_and_note_rows_do_not_confuse_detection() -> None:
    detection = _detect(
        "Date,Description,Amount",
        "2026-09-01,Coffee,-4.50",
        "2026-09-02,Tea,-3.00",
        "Total,,-7.50",
        "End of statement",
    )

    assert detection.questions == ()
    assert len(detection.preview) == 2


def test_cp1252_is_the_fallback_encoding() -> None:
    data = "Date,Description,Amount\n2026-09-01,Café,-4.50\n".encode("cp1252")

    detection = detect_csv(data)

    assert detection.layout.encoding == "cp1252"
    assert detection.preview[0].description == "Café"


def test_utf8_byte_order_mark_is_not_part_of_the_first_column() -> None:
    detection = detect_csv(b"\xef\xbb\xbfDate,Description,Amount\n2026-09-01,Cafe,-4.50\n")

    assert detection.columns[0] == "Date"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "The file is empty."),
        (b" \r\n\t", "The file is empty."),
        (b"%PDF-1.7\n...", "This is a PDF"),
        (b"PK\x03\x04rest-of-zip", "Excel workbook"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "Excel workbook"),
        ("Date,Amount\n".encode("utf-16"), "UTF-16"),
        (b"Date,Amount\n\x00\x01\x02", "isn't a text file"),
        (b"Date,Description\n2026-09-01,\x81\x8d\n", "text encoding isn't supported"),
        (b"one column only\nanother line\n", "No transactions were found"),
        (b"Date,Description,Amount\n", "No transactions were found"),
    ],
)
def test_unreadable_files(data: bytes, message: str) -> None:
    with pytest.raises(StatementParseError, match=message):
        detect_csv(data)


def test_file_size_limit() -> None:
    with pytest.raises(StatementParseError, match="the most Monelyth reads is 20 MB"):
        detect_csv(b"a" * (MAX_FILE_BYTES + 1))


def test_row_limit() -> None:
    data = b"Date,Description,Amount\n" + b"2026-09-01,Coffee,-4.50\n" * MAX_ROWS

    with pytest.raises(StatementParseError, match="more than 100,000 rows"):
        detect_csv(data)


def test_column_limit() -> None:
    data = b"Date,Description,Amount\n" + b"," * 500 + b"\n"

    with pytest.raises(StatementParseError, match="Row 2 has 501 columns"):
        detect_csv(data)


def test_line_of_millions_of_delimiters_is_rejected_before_splitting() -> None:
    data = b"Date,Description,Amount\n" + b"," * 5_000_000

    with pytest.raises(StatementParseError, match="Row 2 has far more than the 64 columns"):
        detect_csv(data)


def test_old_mac_line_endings() -> None:
    detection = detect_csv(b"Date,Description,Amount\r2026-09-01,Coffee,-4.50\r2026-09-02,Tea,-3\r")

    assert [t.description for t in detection.preview] == ["Coffee", "Tea"]


def test_unclosed_quote_hits_the_field_limit() -> None:
    data = b'Date,Description,Amount\n2026-09-01,"' + b"x" * 200_000 + b"\n"

    with pytest.raises(StatementParseError, match="a quote mark is never closed"):
        detect_csv(data)


def test_hostile_quote_storm_fails_cleanly() -> None:
    with pytest.raises(StatementParseError):
        detect_csv(b'"' * 1_000_000)
