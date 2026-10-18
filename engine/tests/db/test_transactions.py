from __future__ import annotations

import datetime
import sqlite3

import pytest

from monelyth_engine.db.accounts import create_account
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.imports import record_import
from monelyth_engine.db.models import (
    Account,
    AccountType,
    CategorySource,
    InsertResult,
    NewTransaction,
)
from monelyth_engine.db.transactions import (
    fingerprints,
    get_transaction,
    insert_transactions,
    list_transactions,
    transaction_date_range,
    update_transaction,
)
from monelyth_engine.ingest.models import RawTransaction, StatementFormat
from tests.db.conftest import ImportStatement, count_rows, raw, sha256_of

TOO_LARGE_FOR_SQLITE = 2**63
"""SQLite integers are signed 64-bit, so binding this fails part-way through a batch."""


def _record(conn: sqlite3.Connection, account_id: int, label: str) -> int:
    return record_import(
        conn,
        account_id=account_id,
        file_name=f"{label}.csv",
        file_sha256=sha256_of(label),
        statement_format=StatementFormat.CSV,
        row_count=3,
    ).id


def _category_id(conn: sqlite3.Connection, name: str) -> int:
    category_id: int = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[
        0
    ]
    return category_id


def test_inserted_rows_are_stored_uncategorized(
    db: sqlite3.Connection, account: Account, import_statement: ImportStatement
) -> None:
    result = import_statement(
        [raw(1, -1299, "SQ *BLUE BOTTLE 0423"), raw(2, 250000, "PAYROLL DEPOSIT")],
        file_label="sept",
        merchants=["Blue Bottle", None],
    )

    assert result == InsertResult(added=2, skipped_duplicates=0)
    stored = list_transactions(db).items
    assert [(t.posted_date, t.amount_cents, t.description_raw, t.merchant) for t in stored] == [
        (datetime.date(2026, 9, 2), 250000, "PAYROLL DEPOSIT", None),
        (datetime.date(2026, 9, 1), -1299, "SQ *BLUE BOTTLE 0423", "Blue Bottle"),
    ]
    first = stored[1]
    assert first.account_id == account.id
    assert first.import_id is not None
    assert first.category_id is None
    assert first.category_source is None
    assert first.confidence is None
    assert first.needs_review is False
    assert first.transfer_group is None


def test_identical_rows_on_the_same_day_are_all_kept(
    db: sqlite3.Connection, import_statement: ImportStatement
) -> None:
    coffee = raw(5, -500, "TIM HORTONS #123")

    result = import_statement([coffee, coffee, raw(5, -500, "TIM HORTONS #456")], file_label="a")

    assert result == InsertResult(added=3, skipped_duplicates=0)


def test_overlapping_statement_only_adds_new_rows(
    db: sqlite3.Connection, import_statement: ImportStatement
) -> None:
    coffee = raw(15, -500, "TIM HORTONS")
    september = [raw(1, -150000, "RENT"), coffee, coffee, raw(20, -4599, "LOBLAWS")]
    mid_september_to_october = [
        coffee,
        coffee,
        raw(20, -4599, "LOBLAWS"),
        raw(2, -150000, "RENT", month=10),
    ]

    assert import_statement(september, file_label="sept") == InsertResult(4, 0)
    assert import_statement(mid_september_to_october, file_label="sept-oct") == InsertResult(1, 3)
    assert count_rows(db, "transactions") == 5


def test_a_third_identical_row_in_a_later_statement_is_added(
    db: sqlite3.Connection, import_statement: ImportStatement
) -> None:
    coffee = raw(15, -500, "TIM HORTONS")

    import_statement([coffee, coffee], file_label="first")
    result = import_statement([coffee, coffee, coffee], file_label="corrected")

    assert result == InsertResult(added=1, skipped_duplicates=2)


def test_bank_ids_decide_duplicates_when_present(
    db: sqlite3.Connection, import_statement: ImportStatement
) -> None:
    import_statement([raw(1, -1299, "BLUE BOTTLE", "FIT-1")], file_label="ofx-1")

    result = import_statement(
        [
            raw(1, -1299, "BLUE BOTTLE COFFEE TORONTO", "FIT-1"),  # bank reworded it: same row
            raw(1, -1299, "BLUE BOTTLE", "FIT-2"),  # identical text, different ID: new row
        ],
        file_label="ofx-2",
    )

    assert result == InsertResult(added=1, skipped_duplicates=1)


def test_same_rows_in_another_account_are_not_duplicates(
    db: sqlite3.Connection, import_statement: ImportStatement
) -> None:
    card = create_account(db, name="Visa", account_type=AccountType.CREDIT_CARD, currency="CAD")
    rows = [raw(1, -1299, "BLUE BOTTLE"), raw(2, -500, "STARBUCKS", "FIT-9")]

    import_statement(rows, file_label="checking")
    result = import_statement(rows, file_label="card", account_id=card.id)

    assert result == InsertResult(added=2, skipped_duplicates=0)


def test_fingerprints_are_deterministic_and_unambiguous() -> None:
    rows = [
        raw(1, -100, "A"),
        raw(1, -100, "A"),
        raw(1, -100, 'A","0'),
        raw(1, -100, "A|0"),
        raw(1, -1000, "A"),
        raw(10, -100, "A"),
        raw(1, -100, "X", "A"),
    ]

    keys = fingerprints(1, rows)

    assert keys == fingerprints(1, rows)
    assert len(set(keys)) == len(rows)
    assert all(len(key) == 64 for key in keys)
    assert set(keys).isdisjoint(fingerprints(2, rows))


def test_failed_insert_rolls_back_the_import_and_its_rows(
    db: sqlite3.Connection, import_statement: ImportStatement
) -> None:
    good = [raw(1, -100, "A"), raw(2, -200, "B")]

    with pytest.raises(OverflowError):
        import_statement([*good, raw(3, TOO_LARGE_FOR_SQLITE, "C")], file_label="sept")

    assert count_rows(db, "imports") == 0
    assert count_rows(db, "transactions") == 0
    assert not db.in_transaction
    # Nothing was left behind, so the same file can be imported once the problem is fixed.
    assert import_statement(good, file_label="sept") == InsertResult(added=2, skipped_duplicates=0)


def test_insert_on_its_own_is_all_or_nothing(db: sqlite3.Connection, account: Account) -> None:
    import_id = _record(db, account.id, "sept")
    rows = [raw(1, -100, "A"), raw(2, TOO_LARGE_FOR_SQLITE, "B")]

    with pytest.raises(OverflowError):
        insert_transactions(
            db,
            account_id=account.id,
            import_id=import_id,
            items=[NewTransaction(row, None) for row in rows],
        )

    assert count_rows(db, "transactions") == 0
    assert not db.in_transaction


def test_empty_statement_adds_nothing(db: sqlite3.Connection, account: Account) -> None:
    import_id = _record(db, account.id, "empty")

    result = insert_transactions(db, account_id=account.id, import_id=import_id, items=[])

    assert result == InsertResult(added=0, skipped_duplicates=0)


def test_unknown_import_is_rejected(db: sqlite3.Connection, account: Account) -> None:
    with pytest.raises(NotFoundError, match="Import 99"):
        insert_transactions(db, account_id=account.id, import_id=99, items=[])


def test_import_from_another_account_is_rejected(db: sqlite3.Connection, account: Account) -> None:
    card = create_account(db, name="Visa", account_type=AccountType.CREDIT_CARD, currency="CAD")
    import_id = _record(db, account.id, "sept")

    with pytest.raises(ValueError, match="belongs to account"):
        insert_transactions(
            db,
            account_id=card.id,
            import_id=import_id,
            items=[NewTransaction(raw(1, -100, "A"), None)],
        )
    assert count_rows(db, "transactions") == 0


@pytest.mark.parametrize("merchant", ["", " Blue Bottle", "Blue Bottle "])
def test_new_transaction_rejects_malformed_merchant(merchant: str) -> None:
    with pytest.raises(ValueError, match="merchant"):
        NewTransaction(RawTransaction(datetime.date(2026, 9, 1), -100, "A"), merchant)


@pytest.fixture
def stored_id(db: sqlite3.Connection, import_statement: ImportStatement) -> int:
    """One transaction that automatic categorization has already guessed at."""
    import_statement([raw(1, -1299, "SQ *BLUE BOTTLE")], file_label="sept", merchants=["Blue"])
    transaction_id: int = db.execute("SELECT id FROM transactions").fetchone()[0]
    db.execute(
        "UPDATE transactions SET category_id = ?, category_source = 'classifier', "
        "confidence = 0.62, needs_review = 1 WHERE id = ?",
        (_category_id(db, "Dining Out"), transaction_id),
    )
    return transaction_id


def test_user_category_overrides_the_automatic_one(db: sqlite3.Connection, stored_id: int) -> None:
    coffee = _category_id(db, "Coffee")

    updated = update_transaction(db, stored_id, category_id=coffee)

    assert updated.category_id == coffee
    assert updated.category_source is CategorySource.USER
    assert updated.confidence is None
    assert updated.needs_review is False
    assert updated.merchant == "Blue"
    assert get_transaction(db, stored_id) == updated


def test_merchant_can_be_renamed(db: sqlite3.Connection, stored_id: int) -> None:
    updated = update_transaction(db, stored_id, merchant="  Blue Bottle ")

    assert updated.merchant == "Blue Bottle"
    assert updated.category_source is CategorySource.CLASSIFIER
    assert updated.needs_review is True


def test_category_and_merchant_change_together(db: sqlite3.Connection, stored_id: int) -> None:
    coffee = _category_id(db, "Coffee")

    updated = update_transaction(db, stored_id, category_id=coffee, merchant="Blue Bottle")

    assert (updated.category_id, updated.merchant) == (coffee, "Blue Bottle")


def test_unknown_category_changes_nothing(db: sqlite3.Connection, stored_id: int) -> None:
    before = get_transaction(db, stored_id)

    with pytest.raises(NotFoundError, match="Category 999"):
        update_transaction(db, stored_id, category_id=999, merchant="Renamed")

    assert get_transaction(db, stored_id) == before


def test_unknown_transaction_is_rejected(db: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="Transaction 5"):
        update_transaction(db, 5, merchant="Anything")


def test_update_needs_a_change(db: sqlite3.Connection, stored_id: int) -> None:
    with pytest.raises(ValueError, match="Give a category"):
        update_transaction(db, stored_id)


def test_blank_merchant_is_rejected(db: sqlite3.Connection, stored_id: int) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        update_transaction(db, stored_id, merchant="   ")


def test_date_range_is_none_without_transactions(db: sqlite3.Connection, account: Account) -> None:
    assert transaction_date_range(db) is None


def test_date_range_spans_every_account(
    db: sqlite3.Connection, account: Account, import_statement: ImportStatement
) -> None:
    card = create_account(db, name="Visa", account_type=AccountType.CREDIT_CARD, currency="CAD")
    import_statement([raw(14, -500, "COFFEE"), raw(2, -500, "COFFEE")], file_label="checking")
    import_statement([raw(28, -900, "BOOKS", month=11)], file_label="card", account_id=card.id)

    assert transaction_date_range(db) == (datetime.date(2026, 9, 2), datetime.date(2026, 11, 28))
