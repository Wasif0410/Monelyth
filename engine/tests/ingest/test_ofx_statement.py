from __future__ import annotations

import codecs
import datetime
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from monelyth_engine.ingest.models import (
    ParsedStatement,
    RawTransaction,
    StatementFormat,
    StatementParseError,
)
from monelyth_engine.ingest.ofx_statement import MAX_FILE_BYTES, parse_ofx

# ofxtools warns about Intuit's private QFX tags. parse_ofx silences that when it is imported,
# but pytest resets warning filters around every test.
pytestmark = pytest.mark.filterwarnings("ignore::UserWarning:ofxtools")

FIXTURES: Final = Path(__file__).parent / "fixtures" / "ofx"

_SGML_HEADER: Final = (
    "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:USASCII\n"
    "CHARSET:{charset}\nCOMPRESSION:NONE\nOLDFILEUID:NONE\nNEWFILEUID:NONE\n\n"
)
_SIGNON: Final = (
    "<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS>"
    "<DTSERVER>20260930<LANGUAGE>ENG</SONRS></SIGNONMSGSRSV1>"
)


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _bank_statement(entries: str, *, acctid: str = "1234567", tranlist: bool = True) -> str:
    tran_list = (
        f"<BANKTRANLIST><DTSTART>20260901<DTEND>20260930{entries}</BANKTRANLIST>"
        if tranlist
        else ""
    )
    return (
        "<STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS>"
        "<STMTRS><CURDEF>CAD"
        f"<BANKACCTFROM><BANKID>000123456<ACCTID>{acctid}<ACCTTYPE>CHECKING</BANKACCTFROM>"
        f"{tran_list}"
        "<LEDGERBAL><BALAMT>100.00<DTASOF>20260930</LEDGERBAL>"
        "</STMTRS></STMTTRNRS>"
    )


def _sgml(body: str, *, charset: str = "NONE") -> str:
    """An OFX 1.x document with a signon and ``body`` as its message sets."""
    return f"{_SGML_HEADER.format(charset=charset)}<OFX>{_SIGNON}{body}</OFX>\n"


def _bank_file(*statements: str, charset: str = "NONE") -> bytes:
    return _sgml(f"<BANKMSGSRSV1>{''.join(statements)}</BANKMSGSRSV1>", charset=charset).encode(
        "ascii"
    )


def _entry(
    *,
    dtposted: str = "20260915",
    trnamt: str = "-4.75",
    fitid: str = "F1",
    name: str | None = "SQ *BLUE BOTTLE",
    memo: str | None = None,
    extra: str = "",
) -> str:
    name_tag = "" if name is None else f"<NAME>{name}"
    memo_tag = "" if memo is None else f"<MEMO>{memo}"
    return (
        f"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>{dtposted}<TRNAMT>{trnamt}<FITID>{fitid}"
        f"{name_tag}{extra}{memo_tag}</STMTTRN>"
    )


def _single(entry: str) -> RawTransaction:
    (transaction,) = parse_ofx(_bank_file(_bank_statement(entry))).transactions
    return transaction


# --- Whole files -------------------------------------------------------------------------


def test_sgml_bank_statement() -> None:
    statement = parse_ofx(_fixture("bank_sgml.ofx"))

    assert statement == ParsedStatement(
        format=StatementFormat.OFX,
        currency="CAD",
        transactions=(
            RawTransaction(datetime.date(2026, 9, 4), 245000, "PAYROLL ACME CORP", "202609040001"),
            RawTransaction(
                datetime.date(2026, 9, 5), -645, "SQ *BLUE BOTTLE 0423 TORONTO ON", "202609050001"
            ),
            # MEMO only, with whitespace around it.
            RawTransaction(
                datetime.date(2026, 9, 7), -8712, "LOBLAWS #1234 TORONTO ON", "202609070001"
            ),
            # NAME is MEMO cut off at "TOR"; &amp; is unescaped.
            RawTransaction(
                datetime.date(2026, 9, 12),
                -4230,
                "TOMMY & LEFEBVRE BISTRO TORONTO ON",
                "202609120001",
            ),
            # 22:30 EST is already the next day in UTC; the bank's own date is kept. NAME and
            # MEMO differ only in case, so the text appears once.
            RawTransaction(
                datetime.date(2026, 9, 15), -1899, "NETFLIX.COM 866-579-7172", "202609150001"
            ),
            RawTransaction(
                datetime.date(2026, 9, 20),
                -125000,
                "ONLINE TRANSFER TO VISA 4520",
                "202609200001",
            ),
        ),
    )


def test_xml_bank_statement() -> None:
    statement = parse_ofx(_fixture("bank_xml.ofx"))

    assert statement.format is StatementFormat.OFX
    assert statement.currency == "USD"
    assert statement.warnings == ()
    assert statement.transactions == (
        # 01:30 JST is still the previous day in UTC; the bank's own date is kept.
        RawTransaction(datetime.date(2026, 9, 1), 42, "INTEREST PAYMENT", "INT-2026-09"),
        RawTransaction(datetime.date(2026, 9, 14), -123456, "WITHDRAWAL", "WD-0914"),
        # No NAME: the PAYEE aggregate's name is used, followed by the memo.
        RawTransaction(
            datetime.date(2026, 9, 21),
            -30000,
            "HARBOURVIEW PROPERTY MGMT CHEQUE 0107",
            "CHK-0107",
        ),
    )


def test_credit_card_qfx_keeps_ofx_signs() -> None:
    """OFX already signs card amounts from the holder's side: purchases out, payments in."""
    statement = parse_ofx(_fixture("credit_card.qfx"))

    assert statement.currency == "CAD"
    assert statement.transactions == (
        RawTransaction(
            datetime.date(2026, 9, 2),
            -2340,
            "UBER *TRIP HELP.UBER.COM",
            "2026090224692160245000012",
        ),
        RawTransaction(
            datetime.date(2026, 9, 10),
            -6497,
            "AMZN Mktp CA*2K4X91 AMZN.CA/PM WA",
            "2026091024692160253000034",
        ),
        RawTransaction(
            datetime.date(2026, 9, 15),
            1599,
            "AMZN Mktp CA*2K4X91 REFUND",
            "2026091524692160258000077",
        ),
        RawTransaction(
            datetime.date(2026, 9, 22), 125000, "PAYMENT - THANK YOU", "2026092224692160265000101"
        ),
    )


def test_crlf_line_endings_give_the_same_result() -> None:
    data = _fixture("bank_sgml.ofx")

    assert parse_ofx(data.replace(b"\n", b"\r\n")) == parse_ofx(data)


def test_utf8_byte_order_mark_is_ignored() -> None:
    data = _fixture("bank_xml.ofx")

    assert parse_ofx(codecs.BOM_UTF8 + data) == parse_ofx(data)


def test_statement_without_transaction_list_is_empty() -> None:
    statement = parse_ofx(_bank_file(_bank_statement("", tranlist=False)))

    assert statement.transactions == ()
    assert statement.currency == "CAD"


# --- Rejected files ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("empty.ofx", "This file is empty."),
        ("not_ofx.csv", "This file isn't an OFX or QFX statement."),
        ("truncated.ofx", "This OFX file is incomplete."),
        ("multi_account.ofx", "This file has 2 accounts. Export one account at a time."),
    ],
)
def test_rejected_fixtures(fixture: str, message: str) -> None:
    with pytest.raises(StatementParseError) as excinfo:
        parse_ofx(_fixture(fixture))

    assert str(excinfo.value).startswith(message)


def test_bank_and_card_statements_count_as_two_accounts() -> None:
    card = _fixture("credit_card.qfx").decode("ascii")
    card_set = card[card.index("<CREDITCARDMSGSRSV1>") : card.index("</OFX>")]
    bank = _bank_file(_bank_statement(_entry())).decode("ascii")
    data = bank.replace("</OFX>", f"{card_set}</OFX>").encode("ascii")

    with pytest.raises(StatementParseError, match="This file has 2 accounts"):
        parse_ofx(data)


def test_two_statements_for_one_account_are_rejected() -> None:
    data = _bank_file(_bank_statement(_entry()), _bank_statement(_entry(fitid="F2")))

    with pytest.raises(StatementParseError, match="2 statements for the same account"):
        parse_ofx(data)


def test_file_without_statements_is_rejected() -> None:
    with pytest.raises(StatementParseError, match="no bank or credit card statement"):
        parse_ofx(_sgml("").encode("ascii"))


def test_investment_statement_is_rejected() -> None:
    investment = (
        "<INVSTMTMSGSRSV1><INVSTMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS>"
        "<INVSTMTRS><DTASOF>20260930<CURDEF>CAD"
        "<INVACCTFROM><BROKERID>broker.example<ACCTID>777</INVACCTFROM>"
        "</INVSTMTRS></INVSTMTTRNRS></INVSTMTMSGSRSV1>"
    )

    with pytest.raises(StatementParseError, match="investment statement"):
        parse_ofx(_sgml(investment).encode("ascii"))


def test_oversized_file_is_rejected_before_parsing() -> None:
    with pytest.raises(StatementParseError, match="larger than 20 MB"):
        parse_ofx(b"<OFX>" + b" " * MAX_FILE_BYTES + b"</OFX>")


def test_body_without_header_is_reported_as_damaged_header() -> None:
    data = _bank_file(_bank_statement(_entry()))
    body = data[data.index(b"<OFX>") :]

    with pytest.raises(StatementParseError, match="header is missing or damaged"):
        parse_ofx(body)


def test_complete_file_breaking_the_spec_is_reported_as_damaged() -> None:
    # TRNAMT is required.
    data = _bank_file(_bank_statement(_entry().replace("<TRNAMT>-4.75", "")))

    with pytest.raises(StatementParseError, match="damaged or doesn't follow the OFX standard"):
        parse_ofx(data)


@pytest.mark.parametrize(
    "data",
    [
        b"   \n\t ",
        b"\x00\xff\xfe" * 100,
        b"<OFX></OFX>",
        b"OFXHEADER:100\n",
        b'<?xml version="1.0"?>\n<OFX></OFX>',
        b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n",
        b"PK\x03\x04" + b"\x00" * 30,
    ],
)
def test_junk_input_raises_only_statement_parse_error(data: bytes) -> None:
    with pytest.raises(StatementParseError):
        parse_ofx(data)


def test_every_truncation_raises_only_statement_parse_error() -> None:
    """A file cut off anywhere either still parses or fails with a user-facing error."""
    data = _fixture("bank_sgml.ofx")
    complete = parse_ofx(data)

    for length in range(len(data)):
        try:
            statement = parse_ofx(data[:length])
        except StatementParseError:
            continue
        # Only a cut inside the trailing whitespace can still succeed, and then nothing is lost.
        assert statement == complete, f"cut at byte {length} parsed differently"


# --- Dates -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dtposted",
    [
        "20260915",
        "202609151230",
        "20260915123000",
        "20260915123000.000",
        "20260915000000.000[-5:EST]",
        "20260915233000.000[-5:EST]",
        "20260915013000.000[+9:JST]",
        "20260915233000[-3.30:NST]",
        "20260915120000[0:GMT]",
        "20260915120000.123[+5.45:NPT]",
    ],
)
def test_posted_date_is_the_date_the_bank_wrote(dtposted: str) -> None:
    assert _single(_entry(dtposted=dtposted)).posted_date == datetime.date(2026, 9, 15)


@pytest.mark.parametrize("dtposted", ["2026-09-15", "15092026", "20260915T1200", "2026091"])
def test_malformed_posted_date_is_rejected(dtposted: str) -> None:
    with pytest.raises(StatementParseError, match="Transaction 1 has a date in a format"):
        _single(_entry(dtposted=dtposted))


def test_impossible_posted_date_is_rejected() -> None:
    with pytest.raises(StatementParseError, match="Transaction 1 has a date that doesn't exist"):
        _single(_entry(dtposted="20260231"))


# --- Amounts -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trnamt", "cents"),
    [
        ("-4.75", -475),
        ("12.5", 1250),
        ("-1250", -125000),
        ("+3.00", 300),
        ("-0.01", -1),
        ("0.10", 10),
        ("0", 0),
        ("-4,75", -475),  # Some European banks use a decimal comma.
        ("123456789.99", 12345678999),
    ],
)
def test_amount_becomes_exact_cents(trnamt: str, cents: int) -> None:
    assert _single(_entry(trnamt=trnamt)).amount_cents == cents


def test_fraction_of_a_cent_is_rejected() -> None:
    with pytest.raises(StatementParseError, match=r"fraction of a cent: -4\.755"):
        _single(_entry(trnamt="-4.755"))


@pytest.mark.parametrize("trnamt", ["NaN", "Infinity", "-Infinity"])
def test_non_numeric_amount_is_rejected(trnamt: str) -> None:
    with pytest.raises(StatementParseError, match="amount that isn't a number"):
        _single(_entry(trnamt=trnamt))


def test_unparseable_amount_is_reported_as_damaged() -> None:
    with pytest.raises(StatementParseError, match="damaged"):
        _single(_entry(trnamt="12.34 CAD"))


def test_error_names_the_transaction_position() -> None:
    entries = _entry(fitid="F1") + _entry(fitid="F2", trnamt="1.001")

    with pytest.raises(StatementParseError, match="Transaction 2 "):
        parse_ofx(_bank_file(_bank_statement(entries)))


# --- Descriptions ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "memo", "description"),
    [
        ("SQ *BLUE BOTTLE 0423", None, "SQ *BLUE BOTTLE 0423"),
        (None, "PAYROLL ACME CORP", "PAYROLL ACME CORP"),
        ("SQ *BLUE BOTTLE 0423", "TORONTO ON", "SQ *BLUE BOTTLE 0423 TORONTO ON"),
        ("NETFLIX.COM", "netflix.com", "NETFLIX.COM"),
        ("NETFLIX.COM", "NETFLIX.COM  866-579-7172", "NETFLIX.COM  866-579-7172"),
        ("UBER *TRIP HELP.UBER.COM", "HELP.UBER.COM", "UBER *TRIP HELP.UBER.COM"),
        ("PRESTO FARE/T4K2", "PRESTO", "PRESTO FARE/T4K2"),
        # NAME cut off mid-word at OFX's 32-character limit.
        (
            "HARBOURVIEW PROPERTY MANAGEMENT ",
            "HARBOURVIEW PROPERTY MANAGEMENT INC RENT",
            "HARBOURVIEW PROPERTY MANAGEMENT INC RENT",
        ),
        ("PAYMENT", "PAY", "PAYMENT PAY"),
        ("  E-TRANSFER  ", "  RENT OCTOBER ", "E-TRANSFER RENT OCTOBER"),
    ],
)
def test_name_and_memo_make_one_description(
    name: str | None, memo: str | None, description: str
) -> None:
    assert _single(_entry(name=name, memo=memo)).description == description


def test_extended_name_replaces_the_short_name() -> None:
    entry = _entry(
        name="GREENLEAF ORGANIC MARKET - QUEE",
        memo="POS PURCHASE",
        extra="<EXTDNAME>GREENLEAF ORGANIC MARKET - QUEEN ST W",
    )

    assert _single(entry).description == "GREENLEAF ORGANIC MARKET - QUEEN ST W POS PURCHASE"


def test_transaction_without_text_uses_its_type_and_warns() -> None:
    statement = parse_ofx(_bank_file(_bank_statement(_entry(name=None))))

    assert statement.transactions[0].description == "DEBIT"
    assert statement.warnings == (
        "1 transaction has no name or memo, so the transaction type (such as DEBIT) is used "
        "as the description.",
    )


# --- External IDs and warnings -----------------------------------------------------------


def test_fitid_becomes_external_id() -> None:
    assert _single(_entry(fitid="  ABC-123  ")).external_id == "ABC-123"


def test_reused_fitid_keeps_the_transaction_without_an_external_id() -> None:
    """Deduplication keys on FITID, so a reused one must not make a real row disappear."""
    entries = (
        _entry(fitid="SAME", trnamt="-1.00")
        + _entry(fitid="SAME", trnamt="-2.00")
        + _entry(fitid="OTHER")
        + _entry(fitid="SAME", trnamt="-3.00")
    )
    statement = parse_ofx(_bank_file(_bank_statement(entries)))

    assert [(t.external_id, t.amount_cents) for t in statement.transactions] == [
        ("SAME", -100),
        (None, -200),
        ("OTHER", -475),
        (None, -300),
    ]
    assert statement.warnings == (
        "2 transactions reuse the bank ID (FITID) of an earlier transaction in this file. "
        "They were kept; check them for duplicates.",
    )


def test_correction_entries_are_skipped_with_a_warning() -> None:
    # OFX fixes the element order: the correction tags come straight after FITID.
    correction = _entry(fitid="F9<CORRECTFITID>F1<CORRECTACTION>DELETE")
    statement = parse_ofx(_bank_file(_bank_statement(_entry() + correction)))

    assert [t.external_id for t in statement.transactions] == ["F1"]
    assert statement.warnings == (
        "Skipped 1 bank correction to transactions from an earlier download.",
    )


# --- Character sets ----------------------------------------------------------------------


def test_declared_windows_1252_is_decoded() -> None:
    data = _bank_file(_bank_statement(_entry(name="CAFE")), charset="1252")
    data = data.replace(b"CAFE", b"CAF\xc9 OLIMPICO")

    statement = parse_ofx(data)

    assert statement.transactions[0].description == "CAFÉ OLIMPICO"
    assert statement.warnings == ()


@pytest.mark.parametrize("version", ["sgml", "xml"])
def test_undeclared_windows_1252_falls_back_with_a_warning(version: str) -> None:
    if version == "sgml":
        data = _bank_file(_bank_statement(_entry(name="CAFE")), charset="NONE")
        data = data.replace(b"CAFE", b"CAF\xc9 OLIMPICO")
        expected = "CAFÉ OLIMPICO"
    else:
        data = _fixture("bank_xml.ofx").replace(b"WITHDRAWAL", b"RETRAIT GUICHET \xc9TS")
        expected = "RETRAIT GUICHET ÉTS"

    statement = parse_ofx(data)

    assert expected in [t.description for t in statement.transactions]
    assert statement.warnings == (
        "Some characters in this file weren't valid UTF-8, so they were read as Windows-1252. "
        "Check accented names in the descriptions.",
    )


def test_utf8_text_is_kept() -> None:
    data = _fixture("bank_xml.ofx").replace(b"WITHDRAWAL", "CAFÉ CRÈME".encode())

    statement = parse_ofx(data)

    assert statement.transactions[1].description == "CAFÉ CRÈME"
    assert statement.warnings == ()


# --- Privacy -----------------------------------------------------------------------------


def test_parsing_writes_no_statement_data_to_logs_or_warnings() -> None:
    """ofxtools logs every value at DEBUG and repeats values in warnings; neither may leak."""
    script = (
        "import logging, sys\n"
        "logging.basicConfig(level=logging.DEBUG)\n"
        "from monelyth_engine.ingest.ofx_statement import parse_ofx\n"
        "with open(sys.argv[1], 'rb') as file:\n"
        "    parse_ofx(file.read())\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "always", "-c", script, str(FIXTURES / "credit_card.qfx")],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )

    assert result.stderr == ""
    assert result.stdout == ""
