from __future__ import annotations

import datetime
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from monelyth_engine.db import maintenance
from monelyth_engine.db.accounts import create_account
from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.connection import connect
from monelyth_engine.db.maintenance import (
    DataCounts,
    ExportedTransaction,
    backup_database,
    count_data,
    erase_all_data,
    exported_transactions,
)
from monelyth_engine.db.models import Account, AccountType
from monelyth_engine.db.transactions import update_transaction
from tests.db.conftest import ImportStatement, count_rows, raw

USER_TABLES = (
    "accounts",
    "imports",
    "transactions",
    "merchant_memory",
    "rules",
    "csv_profiles",
    "chat_messages",
)


@pytest.fixture
def filled(db: sqlite3.Connection, account: Account, import_statement: ImportStatement) -> None:
    """A database with something in every table the user's activity writes to."""
    import_statement(
        [raw(1, -1_299, "SQ *BLUE BOTTLE"), raw(2, 250_000, "PAYROLL")],
        file_label="sept",
        merchants=["Blue Bottle", None],
    )
    groceries = next(c for c in list_categories(db) if c.name == "Groceries")
    db.execute("INSERT INTO categories (name, kind) VALUES ('Pets', 'expense')")
    db.execute(
        "INSERT INTO merchant_memory VALUES ('Loblaws', ?, 'user', '2026-10-01T00:00:00Z')",
        (groceries.id,),
    )
    db.execute(
        "INSERT INTO rules (pattern, match_type, category_id, created_by) "
        "VALUES ('loblaws', 'contains', ?, 'user')",
        (groceries.id,),
    )
    db.execute("INSERT INTO csv_profiles VALUES ('abc123', '{}')")
    db.execute(
        "INSERT INTO chat_messages (conversation_id, role, content, created_at) "
        "VALUES ('c1', 'user', 'How much on coffee?', '2026-10-01T00:00:00Z')"
    )


def test_count_data(db: sqlite3.Connection, account: Account, filled: None) -> None:
    create_account(db, name="Savings", account_type=AccountType.SAVINGS, currency="CAD")

    assert count_data(db) == DataCounts(accounts=2, transactions=2)


def test_count_data_on_an_empty_database(db: sqlite3.Connection) -> None:
    assert count_data(db) == DataCounts(accounts=0, transactions=0)


def test_backup_is_a_complete_self_contained_copy(
    db: sqlite3.Connection, filled: None, tmp_path: Path
) -> None:
    target = tmp_path / "copy.db"

    backup_database(db, target)

    assert not target.with_name("copy.db-wal").exists()
    with closing(sqlite3.connect(target)) as copy:
        # A rollback-journal file, so it is complete on its own without a -wal file.
        assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        for table in (*USER_TABLES, "categories"):
            assert count_rows(copy, table) == count_rows(db, table)


def test_backup_refuses_to_overwrite(db: sqlite3.Connection, tmp_path: Path) -> None:
    target = tmp_path / "copy.db"
    target.write_text("keep me")

    with pytest.raises(FileExistsError):
        backup_database(db, target)

    assert target.read_text() == "keep me"


def test_exported_transactions_have_names_oldest_first(
    db: sqlite3.Connection, account: Account, filled: None
) -> None:
    payroll = db.execute("SELECT id FROM transactions WHERE amount_cents > 0").fetchone()[0]
    salary = next(c for c in list_categories(db) if c.name == "Salary")
    update_transaction(db, payroll, category_id=salary.id)

    rows = list(exported_transactions(db))

    assert rows == [
        ExportedTransaction(
            posted_date=datetime.date(2026, 9, 1),
            account="Main Checking",
            description="SQ *BLUE BOTTLE",
            merchant="Blue Bottle",
            category=None,
            amount_cents=-1_299,
            currency="CAD",
        ),
        ExportedTransaction(
            posted_date=datetime.date(2026, 9, 2),
            account="Main Checking",
            description="PAYROLL",
            merchant=None,
            category="Salary",
            amount_cents=250_000,
            currency="CAD",
        ),
    ]


def test_erase_empties_every_table_and_restores_the_seed(
    db: sqlite3.Connection, filled: None, tmp_path: Path
) -> None:
    with closing(connect(tmp_path / "fresh.db")) as fresh:
        fresh_categories = list_categories(fresh)

    deleted = erase_all_data(db)

    assert deleted == DataCounts(accounts=1, transactions=2)
    for table in USER_TABLES:
        assert count_rows(db, table) == 0, table
    assert list_categories(db) == fresh_categories
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    # The database stays usable, and new rows start from ID 1 as in a new database.
    account = create_account(db, name="New", account_type=AccountType.CHECKING, currency="CAD")
    assert account.id == 1


def test_erase_on_an_empty_database_changes_nothing(db: sqlite3.Connection) -> None:
    before = list_categories(db)

    assert erase_all_data(db) == DataCounts(accounts=0, transactions=0)
    assert list_categories(db) == before


def test_erase_is_all_or_nothing(
    db: sqlite3.Connection, filled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = {table: count_rows(db, table) for table in (*USER_TABLES, "categories")}
    # A seed row that breaks a constraint makes the erase fail after every table was emptied.
    monkeypatch.setattr(
        maintenance,
        "_fresh_seed_rows",
        lambda: {"categories": (("name", "kind"), [("Broken", "not-a-kind")])},
    )

    with pytest.raises(sqlite3.IntegrityError):
        erase_all_data(db)

    assert {table: count_rows(db, table) for table in before} == before


def test_erase_shrinks_the_file(db: sqlite3.Connection, db_path: Path) -> None:
    db.executemany(
        "INSERT INTO chat_messages (conversation_id, role, content, created_at) "
        "VALUES ('c', 'user', ?, '2026-10-01T00:00:00Z')",
        [("x" * 4_000,) for _ in range(200)],
    )
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    size_before = db_path.stat().st_size

    erase_all_data(db)

    assert db_path.stat().st_size < size_before / 10
    assert db_path.with_name(f"{db_path.name}-wal").stat().st_size == 0
