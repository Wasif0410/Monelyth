from __future__ import annotations

import sqlite3

import pytest

from monelyth_engine.db.accounts import create_account, get_account, list_accounts
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.models import Account, AccountType


def test_create_and_list_accounts(db: sqlite3.Connection) -> None:
    card = create_account(
        db,
        name="  Visa Infinite ",
        account_type=AccountType.CREDIT_CARD,
        currency="CAD",
        institution=" TD ",
    )
    savings = create_account(db, name="Savings", account_type=AccountType.SAVINGS, currency="USD")

    assert card == Account(
        id=card.id,
        name="Visa Infinite",
        institution="TD",
        type=AccountType.CREDIT_CARD,
        currency="CAD",
    )
    assert savings.institution is None
    assert list_accounts(db) == [card, savings]
    assert get_account(db, savings.id) == savings


def test_blank_institution_is_stored_as_none(db: sqlite3.Connection) -> None:
    account = create_account(
        db, name="Cash", account_type=AccountType.OTHER, currency="CAD", institution="   "
    )

    assert account.institution is None


def test_list_accounts_is_empty_at_first(db: sqlite3.Connection) -> None:
    assert list_accounts(db) == []


def test_blank_name_is_rejected(db: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="name"):
        create_account(db, name="   ", account_type=AccountType.CHECKING, currency="CAD")


@pytest.mark.parametrize("currency", ["", "cad", "CA", "CADX", "C4D"])
def test_invalid_currency_is_rejected(db: sqlite3.Connection, currency: str) -> None:
    with pytest.raises(ValueError, match="three-letter code"):
        create_account(db, name="Checking", account_type=AccountType.CHECKING, currency=currency)


def test_get_missing_account_raises(db: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="Account 42 does not exist"):
        get_account(db, 42)
