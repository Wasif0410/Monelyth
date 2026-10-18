from __future__ import annotations

import datetime
import sqlite3

import pytest

from monelyth_engine.db.accounts import (
    AccountDeletion,
    AccountStats,
    account_stats,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
)
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.models import Account, AccountType
from tests.db.conftest import ImportStatement, count_rows, raw


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


def test_update_renames_and_sets_institution(db: sqlite3.Connection, account: Account) -> None:
    updated = update_account(db, account.id, name="  Joint Checking ", institution=" RBC ")

    assert updated == Account(
        id=account.id,
        name="Joint Checking",
        institution="RBC",
        type=account.type,
        currency=account.currency,
    )
    assert get_account(db, account.id) == updated


@pytest.mark.parametrize("institution", [None, "", "   "])
def test_update_can_clear_the_institution(
    db: sqlite3.Connection, account: Account, institution: str | None
) -> None:
    update_account(db, account.id, name=account.name, institution="RBC")

    updated = update_account(db, account.id, name=account.name, institution=institution)

    assert updated.institution is None


def test_update_rejects_a_blank_name(db: sqlite3.Connection, account: Account) -> None:
    with pytest.raises(ValueError, match="name"):
        update_account(db, account.id, name="  ", institution=None)

    assert get_account(db, account.id) == account


def test_update_missing_account_raises(db: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="Account 42 does not exist"):
        update_account(db, 42, name="Anything", institution=None)


def test_delete_removes_the_account_its_imports_and_transactions(
    db: sqlite3.Connection, account: Account, import_statement: ImportStatement
) -> None:
    other = create_account(db, name="Savings", account_type=AccountType.SAVINGS, currency="CAD")
    import_statement([raw(1, -500, "COFFEE"), raw(2, -700, "LUNCH")], file_label="sept")
    import_statement([raw(3, 900, "REFUND")], file_label="oct")
    import_statement([raw(4, 10_000, "INTEREST")], file_label="other", account_id=other.id)

    deletion = delete_account(db, account.id)

    assert deletion == AccountDeletion(imports=2, transactions=3)
    assert list_accounts(db) == [other]
    assert count_rows(db, "imports") == 1
    assert count_rows(db, "transactions") == 1
    assert db.execute("SELECT account_id FROM transactions").fetchone()[0] == other.id


def test_delete_missing_account_raises(db: sqlite3.Connection, account: Account) -> None:
    with pytest.raises(NotFoundError, match="Account 42 does not exist"):
        delete_account(db, 42)

    assert list_accounts(db) == [account]


def test_delete_is_all_or_nothing(
    db: sqlite3.Connection, account: Account, import_statement: ImportStatement
) -> None:
    import_statement([raw(1, -500, "COFFEE")], file_label="sept")
    # Something the delete doesn't know about still points at the account, so removing the
    # account itself fails after its transactions and imports were already deleted.
    db.execute("CREATE TABLE notes (account_id INTEGER NOT NULL REFERENCES accounts(id)) STRICT")
    db.execute("INSERT INTO notes VALUES (?)", (account.id,))

    with pytest.raises(sqlite3.IntegrityError):
        delete_account(db, account.id)

    assert list_accounts(db) == [account]
    assert count_rows(db, "imports") == 1
    assert count_rows(db, "transactions") == 1


def test_stats_sum_each_accounts_transactions(
    db: sqlite3.Connection, account: Account, import_statement: ImportStatement
) -> None:
    empty = create_account(db, name="Savings", account_type=AccountType.SAVINGS, currency="CAD")
    card = create_account(db, name="Visa", account_type=AccountType.CREDIT_CARD, currency="CAD")
    import_statement(
        [raw(3, 250_000, "PAYROLL"), raw(14, -4_210, "GROCER"), raw(2, -1_299, "COFFEE", month=10)],
        file_label="checking",
    )
    import_statement([raw(20, -8_000, "AIRLINE")], file_label="card", account_id=card.id)

    stats = account_stats(db)

    assert stats == {
        account.id: AccountStats(
            transaction_count=3,
            latest_transaction_date=datetime.date(2026, 10, 2),
            net_amount_cents=244_491,
        ),
        card.id: AccountStats(
            transaction_count=1,
            latest_transaction_date=datetime.date(2026, 9, 20),
            net_amount_cents=-8_000,
        ),
    }
    assert empty.id not in stats
    assert account_stats(db, card.id) == {card.id: stats[card.id]}
    assert account_stats(db, empty.id) == {}
