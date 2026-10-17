from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from monelyth_engine.db.accounts import create_account, list_accounts
from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.connection import connect
from monelyth_engine.db.errors import SchemaVersionError
from monelyth_engine.db.models import Account, AccountType, CategoryKind
from monelyth_engine.db.schema import (
    Migration,
    bundled_migrations,
    latest_version,
    migrate,
    schema_version,
)
from tests.db.conftest import count_rows

EXPECTED_TABLES = {
    "accounts",
    "categories",
    "imports",
    "transactions",
    "merchant_memory",
    "rules",
    "csv_profiles",
    "chat_messages",
}

DEFAULT_CATEGORIES = {
    "Salary": CategoryKind.INCOME,
    "Other Income": CategoryKind.INCOME,
    "Rent/Mortgage": CategoryKind.EXPENSE,
    "Utilities": CategoryKind.EXPENSE,
    "Groceries": CategoryKind.EXPENSE,
    "Dining Out": CategoryKind.EXPENSE,
    "Coffee": CategoryKind.EXPENSE,
    "Transport": CategoryKind.EXPENSE,
    "Gas": CategoryKind.EXPENSE,
    "Rideshare": CategoryKind.EXPENSE,
    "Shopping": CategoryKind.EXPENSE,
    "Subscriptions": CategoryKind.EXPENSE,
    "Entertainment": CategoryKind.EXPENSE,
    "Health": CategoryKind.EXPENSE,
    "Education": CategoryKind.EXPENSE,
    "Travel": CategoryKind.EXPENSE,
    "Fees & Interest": CategoryKind.EXPENSE,
    "Gifts & Donations": CategoryKind.EXPENSE,
    "Transfers": CategoryKind.TRANSFER,
    "Other": CategoryKind.EXPENSE,
}


def _names(conn: sqlite3.Connection, object_type: str) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_schema WHERE type = ? AND name NOT LIKE 'sqlite_%'",
        (object_type,),
    ).fetchall()
    return {row["name"] for row in rows}


def _raw_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, autocommit=True)
    conn.row_factory = sqlite3.Row
    return conn


def test_bundled_migrations_are_numbered_from_one() -> None:
    migrations = bundled_migrations()

    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "001_init.sql"
    assert latest_version() == len(migrations)


def test_connect_creates_the_schema_from_an_empty_file(db: sqlite3.Connection) -> None:
    assert schema_version(db) == latest_version()
    assert _names(db, "table") == EXPECTED_TABLES
    assert {"ix_tx_account_date", "ix_tx_category_date"} <= _names(db, "index")


def test_migrating_again_changes_nothing(db_path: Path) -> None:
    with closing(connect(db_path)) as conn:
        create_account(conn, name="Savings", account_type=AccountType.SAVINGS, currency="CAD")

    with closing(_raw_connection(db_path)) as conn:
        assert migrate(conn) == latest_version()
        assert conn.total_changes == 0

    with closing(connect(db_path)) as conn:
        assert [a.name for a in list_accounts(conn)] == ["Savings"]
        assert count_rows(conn, "categories") == len(DEFAULT_CATEGORIES)


def test_newer_database_is_refused_and_left_untouched(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE from_the_future (x INTEGER)")
        conn.execute(f"PRAGMA user_version = {latest_version() + 1}")
        conn.commit()
    before = db_path.read_bytes()

    with pytest.raises(SchemaVersionError, match="created by a newer version of Monelyth"):
        connect(db_path)

    assert db_path.read_bytes() == before
    assert not db_path.with_name(db_path.name + "-wal").exists()


def test_each_migration_commits_on_its_own(db_path: Path) -> None:
    first = Migration(1, "001_a.sql", "CREATE TABLE a (x INTEGER);")
    broken = Migration(
        2, "002_b.sql", "CREATE TABLE b (x INTEGER); INSERT INTO missing VALUES (1);"
    )
    fixed = Migration(2, "002_b.sql", "CREATE TABLE b (x INTEGER);")

    with closing(_raw_connection(db_path)) as conn:
        with pytest.raises(sqlite3.OperationalError, match="missing"):
            migrate(conn, [first, broken])

        assert schema_version(conn) == 1
        assert _names(conn, "table") == {"a"}
        assert not conn.in_transaction

        assert migrate(conn, [first, fixed]) == 2
        assert _names(conn, "table") == {"a", "b"}


def test_default_categories_are_seeded_with_kinds(db: sqlite3.Connection) -> None:
    categories = list_categories(db)

    assert {c.name: c.kind for c in categories} == DEFAULT_CATEGORIES
    assert [c.name for c in categories][:2] == ["Salary", "Other Income"]
    assert all(c.parent_id is None for c in categories)


def test_seeding_is_idempotent(db: sqlite3.Connection) -> None:
    init_sql = bundled_migrations()[0].sql
    seed_sql = init_sql[init_sql.index("INSERT INTO categories") :]

    db.executescript(seed_sql)
    db.executescript(seed_sql)

    assert count_rows(db, "categories") == len(DEFAULT_CATEGORIES)


def test_foreign_keys_are_enforced(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO transactions (account_id, posted_date, amount_cents, description_raw, "
            "fingerprint) VALUES (999, '2026-09-01', -100, 'Coffee', 'fp')"
        )


@pytest.mark.parametrize("amount", ["12.99", 12.99, "twelve"])
def test_amounts_must_be_integers(
    db: sqlite3.Connection, account: Account, amount: str | float
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=r"cannot store \w+ value in INTEGER column"):
        db.execute(
            "INSERT INTO transactions (account_id, posted_date, amount_cents, description_raw, "
            "fingerprint) VALUES (?, '2026-09-01', ?, 'Coffee', 'fp')",
            (account.id, amount),
        )


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO accounts (name, type, currency) VALUES ('A', 'loan', 'CAD')",
        "INSERT INTO categories (name, kind) VALUES ('X', 'savings')",
        "INSERT INTO chat_messages (conversation_id, role, content, created_at) "
        "VALUES ('c', 'system', 'hi', '2026-09-01T00:00:00+00:00')",
    ],
)
def test_check_constraints_reject_unknown_values(db: sqlite3.Connection, statement: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        db.execute(statement)
