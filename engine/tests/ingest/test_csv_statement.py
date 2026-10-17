"""End-to-end tests over realistic (and entirely fake) bank exports in ``fixtures/csv``.

Each case runs the real import flow: detect the layout, answer the open questions the way a
user would, then parse every row and compare against hand-checked values.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from monelyth_engine.ingest.csv_statement import (
    CsvLayout,
    CsvLayoutDraft,
    CsvQuestionKind,
    DebitCredit,
    SignedAmount,
    detect_csv,
    parse_csv,
)
from monelyth_engine.ingest.models import RawTransaction, StatementFormat

FIXTURES = Path(__file__).parent / "fixtures" / "csv"


@dataclass(frozen=True)
class Case:
    fixture: str
    draft: CsvLayoutDraft
    columns: tuple[str, ...]
    transactions: tuple[tuple[str, int, str], ...]
    """``(ISO date, cents, description)`` for every row, after the answers are applied."""
    questions: tuple[CsvQuestionKind, ...] = ()
    answers: dict[str, Any] = dataclasses.field(default_factory=dict[str, Any])
    """What the user picks in the UI to settle the questions."""
    warnings: tuple[str, ...] = ()


def _draft(**values: Any) -> CsvLayoutDraft:
    defaults: dict[str, Any] = {
        "encoding": "utf-8-sig",
        "delimiter": ",",
        "skip_rows": 0,
        "has_header": True,
        "date_column": 0,
        "description_column": 1,
        "decimal_separator": ".",
        "invert_signs": False,
    }
    return CsvLayoutDraft(**(defaults | values))


CASES = [
    Case(
        # Signed amount column, ISO dates, UTF-8 with a byte-order mark, CRLF line endings.
        fixture="northwind_checking.csv",
        draft=_draft(amount=SignedAmount(2), date_format="%Y-%m-%d"),
        columns=("Date", "Description", "Amount", "Balance"),
        transactions=(
            ("2026-09-01", 245000, "PAYROLL NORTHWIND TRADERS"),
            ("2026-09-02", -575, "SQ *BLUE BOTTLE COFFEE"),
            ("2026-09-03", -145000, "RENT - 12 EXAMPLE ST, UNIT 4"),
            ("2026-09-05", -8213, "CITY POWER & LIGHT"),
            ("2026-09-08", -20000, "ONLINE TRANSFER TO SAVINGS"),
            ("2026-09-12", -6340, "GROCERY MART #0042"),
        ),
    ),
    Case(
        # Separate withdrawal and deposit columns, MM/DD/YYYY, dollar signs, blank cells.
        fixture="maple_savings.csv",
        draft=_draft(amount=DebitCredit(2, 3), date_format="%m/%d/%Y"),
        columns=("Transaction Date", "Description", "Withdrawals", "Deposits", "Balance"),
        transactions=(
            ("2026-09-02", -450, "COFFEE HOUSE #12"),
            ("2026-09-04", 25000, "E-TRANSFER RECEIVED"),
            ("2026-09-15", -9620, "HYDRO BILL PAYMENT"),
            ("2026-09-20", 85, "INTEREST"),
            ("2026-09-28", -6000, "ATM WITHDRAWAL"),
        ),
    ),
    Case(
        # Semicolons, DD.MM.YYYY, decimal commas, German headers, posting and value dates.
        fixture="beispielbank_giro.csv",
        draft=_draft(
            delimiter=";",
            description_column=2,
            amount=SignedAmount(3),
            date_format="%d.%m.%Y",
            decimal_separator=",",
        ),
        columns=("Buchungstag", "Wertstellung", "Beschreibung", "Betrag (EUR)", "Saldo (EUR)"),
        transactions=(
            ("2026-09-01", 320000, "Gehalt Beispiel GmbH"),
            ("2026-09-03", -4567, "REWE Markt Musterstadt"),
            ("2026-09-15", -115000, "Miete September"),
            ("2026-09-22", -380, "Bäckerei Schmidt"),
        ),
    ),
    Case(
        # Account details above the header, DD-Mon-YYYY dates and a "Total" line at the end.
        fixture="fictional_federal_preamble.csv",
        draft=_draft(skip_rows=4, amount=SignedAmount(2), date_format="%d-%b-%Y"),
        columns=("Posted Date", "Payee", "Amount"),
        transactions=(
            ("2026-09-05", -1599, "STREAMFLIX SUBSCRIPTION"),
            ("2026-09-11", -4820, "FUEL STOP 881"),
            ("2026-09-18", 2499, "REFUND - EXAMPLE OUTFITTERS"),
            ("2026-09-27", -1235, "PHARMACY PLUS"),
        ),
        warnings=(
            'Skipped row 10 because it looks like a summary line ("Total"), not a transaction.',
        ),
    ),
    Case(
        # No header at all: date, description, debit, credit, balance.
        fixture="example_trust_no_header.csv",
        draft=_draft(has_header=False, amount=DebitCredit(2, 3), date_format="%m/%d/%Y"),
        columns=("Column 1", "Column 2", "Column 3", "Column 4", "Column 5"),
        questions=(CsvQuestionKind.COLUMNS_GUESSED,),
        transactions=(
            ("2026-09-03", -450, "COFFEE HOUSE #12"),
            ("2026-09-05", 120000, "PAYROLL DEPOSIT"),
            ("2026-09-14", -8216, "GROCERY MART #0042"),
            ("2026-09-21", -5500, "PHONE CO MONTHLY"),
            ("2026-09-30", -400, "MONTHLY ACCOUNT FEE"),
        ),
    ),
    Case(
        # A credit card that lists purchases as positive and the payment as negative.
        fixture="contoso_card.csv",
        draft=_draft(
            date_column=1,
            description_column=2,
            amount=SignedAmount(4),
            date_format="%m/%d/%Y",
            invert_signs=None,
        ),
        columns=("Transaction Date", "Post Date", "Description", "Category", "Amount"),
        questions=(CsvQuestionKind.SIGN_CONVENTION_UNKNOWN,),
        answers={"invert_signs": True},
        transactions=(
            ("2026-09-02", -645, "SQ *CORNER BAKERY"),
            ("2026-09-05", -1820, "RIDESHARE TRIP"),
            ("2026-09-11", -3299, "ONLINE BOOKSTORE"),
            ("2026-09-15", 25000, "PAYMENT THANK YOU"),
            ("2026-09-19", -1599, "STREAMFLIX SUBSCRIPTION"),
        ),
    ),
    Case(
        # Windows-1252 text with accents and a euro sign, French headers, DD/MM/YYYY,
        # debit/credit columns, decimal commas and a no-break space as thousands separator.
        fixture="banque_imaginaire_cp1252.csv",
        draft=_draft(
            encoding="cp1252",
            delimiter=";",
            amount=DebitCredit(2, 3),
            date_format="%d/%m/%Y",
            decimal_separator=",",
        ),
        columns=("Date", "Libellé", "Débit", "Crédit"),
        transactions=(
            ("2026-09-02", -420, "Café Crème Paris"),
            ("2026-09-05", 125000, "Virement reçu Société Fictive"),
            ("2026-09-14", -1250, "Pâtisserie Hélène"),
            ("2026-09-23", -6890, "Prélèvement Électricité Imaginaire"),
        ),
    ),
    Case(
        # Unsigned amounts that carry CR/DR suffixes, and DD Mon YYYY dates.
        fixture="harbour_bank_cr_dr.csv",
        draft=_draft(amount=SignedAmount(2), date_format="%d %b %Y"),
        columns=("Date", "Transaction Details", "Amount"),
        transactions=(
            ("2026-09-02", -2345, "CARD PURCHASE GROCERY MART"),
            ("2026-09-04", 210000, "SALARY NORTHWIND TRADERS"),
            ("2026-09-09", -3500, "DIRECT DEBIT GYM CLUB"),
            ("2026-09-16", -4000, "CASH WITHDRAWAL"),
        ),
    ),
    Case(
        # Tabs, negatives in parentheses, Payee and Memo columns, an opening-balance line and a
        # blank row in the middle.
        fixture="lakeside_tabs.tsv",
        draft=_draft(delimiter="\t", amount=SignedAmount(3), date_format="%Y/%m/%d"),
        columns=("Date", "Payee", "Memo", "Amount"),
        transactions=(
            ("2026-09-02", -1840, "THE GREEN GROCER"),
            ("2026-09-09", -4100, "CITY WATER"),
            ("2026-09-12", 180000, "EMPLOYER INC"),
        ),
        warnings=(
            'Skipped row 2 because it looks like a summary line ("Opening balance"), not a '
            "transaction.",
            "Skipped 1 blank row.",
        ),
    ),
]


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _expected(case: Case) -> tuple[RawTransaction, ...]:
    return tuple(
        RawTransaction(datetime.date.fromisoformat(day), cents, description)
        for day, cents, description in case.transactions
    )


def _confirmed_layout(case: Case) -> CsvLayout:
    layout = dataclasses.replace(case.draft, **case.answers).to_layout()
    assert layout is not None
    return layout


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_detects_the_layout(case: Case) -> None:
    detection = detect_csv(_read(case.fixture))

    assert detection.layout == case.draft
    assert detection.columns == case.columns
    assert tuple(question.kind for question in detection.questions) == case.questions


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_parses_every_row(case: Case) -> None:
    statement = parse_csv(_read(case.fixture), _confirmed_layout(case))

    assert statement.format is StatementFormat.CSV
    assert statement.transactions == _expected(case)
    assert statement.warnings == case.warnings
    assert statement.currency is None


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.draft.to_layout() is not None], ids=lambda c: c.fixture
)
def test_complete_layout_comes_with_a_preview(case: Case) -> None:
    assert detect_csv(_read(case.fixture)).preview == _expected(case)


def test_no_preview_until_the_questions_are_answered() -> None:
    detection = detect_csv(_read("contoso_card.csv"))

    assert detection.layout.to_layout() is None
    assert detection.preview == ()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_saved_profile_imports_the_same_rows(case: Case) -> None:
    saved = json.dumps(_confirmed_layout(case).to_dict())

    statement = parse_csv(_read(case.fixture), CsvLayout.from_dict(json.loads(saved)))

    assert statement.transactions == _expected(case)


def test_every_header_signature_is_distinct() -> None:
    signatures = [detect_csv(_read(case.fixture)).header_signature for case in CASES]
    with_header = [s for s in signatures if s is not None]

    assert len(set(with_header)) == len(with_header) == len(CASES) - 1
    assert all(len(signature) == 64 for signature in with_header)
