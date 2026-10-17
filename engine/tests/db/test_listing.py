from __future__ import annotations

import datetime
import sqlite3
from typing import Any

import pytest

from monelyth_engine.db.accounts import create_account
from monelyth_engine.db.models import Account, AccountType, TransactionFilter, TransactionPage
from monelyth_engine.db.transactions import list_transactions, update_transaction
from tests.db.conftest import ImportStatement, raw

NEWEST_FIRST = [
    "NETFLIX.COM",  # Oct 1
    "PAYROLL",  # Sep 30
    "METRO #55",  # Sep 15
    "100% PURE JUICE",  # Sep 10, stored last of that day
    "CAFÉ DEPOT MONTREAL",  # Sep 10
    "LOBLAWS #1022",  # Sep 10, stored first of that day
    "RENT SEPT",  # Sep 1
]


@pytest.fixture
def card(db: sqlite3.Connection) -> Account:
    return create_account(db, name="Visa", account_type=AccountType.CREDIT_CARD, currency="CAD")


@pytest.fixture
def groceries(db: sqlite3.Connection) -> int:
    category_id: int = db.execute("SELECT id FROM categories WHERE name = 'Groceries'").fetchone()[
        0
    ]
    return category_id


@pytest.fixture(autouse=True)
def _stored(
    db: sqlite3.Connection, card: Account, groceries: int, import_statement: ImportStatement
) -> None:
    import_statement(
        [
            raw(1, -150000, "RENT SEPT"),
            raw(10, -4599, "LOBLAWS #1022"),
            raw(10, -1250, "CAFÉ DEPOT MONTREAL"),
            raw(30, 250000, "PAYROLL"),
            raw(1, -999, "NETFLIX.COM", month=10),
        ],
        file_label="checking",
        merchants=["Landlord", "Loblaws", "Café Dépôt", None, "Netflix"],
    )
    import_statement(
        [raw(10, -3000, "100% PURE JUICE"), raw(15, -8000, "METRO #55")],
        file_label="card",
        account_id=card.id,
        merchants=[None, "Metro"],
    )
    for description in ("LOBLAWS #1022", "METRO #55"):
        transaction_id: int = db.execute(
            "SELECT id FROM transactions WHERE description_raw = ?", (description,)
        ).fetchone()[0]
        update_transaction(db, transaction_id, category_id=groceries)


def _descriptions(page: TransactionPage) -> list[str]:
    return [t.description_raw for t in page.items]


def _matching(conn: sqlite3.Connection, **conditions: Any) -> list[str]:
    page = list_transactions(conn, TransactionFilter(**conditions))
    assert page.total == len(page.items)
    return _descriptions(page)


def test_lists_everything_newest_first_with_a_stable_tiebreak(db: sqlite3.Connection) -> None:
    page = list_transactions(db)

    assert _descriptions(page) == NEWEST_FIRST
    assert page.total == len(NEWEST_FIRST)


def test_filters_by_account(db: sqlite3.Connection, account: Account, card: Account) -> None:
    assert _matching(db, account_id=card.id) == ["METRO #55", "100% PURE JUICE"]
    assert len(_matching(db, account_id=account.id)) == 5


def test_date_bounds_are_inclusive(db: sqlite3.Connection) -> None:
    sept_10 = datetime.date(2026, 9, 10)
    sept_15 = datetime.date(2026, 9, 15)

    assert _matching(db, date_from=sept_10) == NEWEST_FIRST[:6]
    assert _matching(db, date_to=sept_10) == NEWEST_FIRST[3:]
    assert _matching(db, date_from=sept_10, date_to=sept_15) == NEWEST_FIRST[2:6]
    assert _matching(db, date_from=sept_15, date_to=sept_10) == []


def test_filters_by_category(db: sqlite3.Connection, groceries: int) -> None:
    assert _matching(db, category_id=groceries) == ["METRO #55", "LOBLAWS #1022"]


@pytest.mark.parametrize(
    ("search", "expected"),
    [
        ("loblaws", ["LOBLAWS #1022"]),  # description, any case
        ("LANDLORD", ["RENT SEPT"]),  # merchant only
        ("café", ["CAFÉ DEPOT MONTREAL"]),  # non-ASCII case folding
        ("dépôt", ["CAFÉ DEPOT MONTREAL"]),  # accented merchant name
        ("%", ["100% PURE JUICE"]),  # wildcard characters match literally
        ("_", []),
        ("  netflix ", ["NETFLIX.COM"]),  # surrounding spaces are ignored
    ],
)
def test_search_is_case_insensitive_over_description_and_merchant(
    db: sqlite3.Connection, search: str, expected: list[str]
) -> None:
    assert _matching(db, search=search) == expected


def test_blank_search_matches_everything(db: sqlite3.Connection) -> None:
    assert _matching(db, search="   ") == NEWEST_FIRST


def test_filters_combine(db: sqlite3.Connection, card: Account, groceries: int) -> None:
    assert _matching(db, account_id=card.id, category_id=groceries, search="metro") == ["METRO #55"]
    assert _matching(db, account_id=card.id, search="loblaws") == []


def test_pages_cover_every_row_exactly_once(db: sqlite3.Connection) -> None:
    pages = [list_transactions(db, limit=3, offset=offset) for offset in (0, 3, 6)]

    assert [len(page.items) for page in pages] == [3, 3, 1]
    assert {page.total for page in pages} == {len(NEWEST_FIRST)}
    assert [d for page in pages for d in _descriptions(page)] == NEWEST_FIRST


def test_page_past_the_end_is_empty_but_keeps_the_total(db: sqlite3.Connection) -> None:
    page = list_transactions(db, TransactionFilter(search="o"), limit=10, offset=50)

    assert page.items == ()
    assert page.total == 6


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (-1, 0), (10, -1)])
def test_invalid_paging_is_rejected(db: sqlite3.Connection, limit: int, offset: int) -> None:
    with pytest.raises(ValueError, match=r"limit|offset"):
        list_transactions(db, limit=limit, offset=offset)
