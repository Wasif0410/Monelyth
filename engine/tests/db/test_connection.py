from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from monelyth_engine.db.accounts import create_account, list_accounts
from monelyth_engine.db.atomic import atomic, read_snapshot
from monelyth_engine.db.connection import connect, connect_readonly
from monelyth_engine.db.errors import SchemaVersionError
from monelyth_engine.db.models import Account, AccountType
from monelyth_engine.db.transactions import list_transactions
from tests.db.conftest import count_rows


def test_connect_sets_up_the_connection(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert isinstance(db.execute("SELECT 1 AS one").fetchone(), sqlite3.Row)
    assert db.execute("SELECT casefold('CAFÉ'), casefold(NULL)").fetchone()[:] == ("café", None)


def test_readonly_connection_reads_but_refuses_writes(db_path: Path, account: Account) -> None:
    with closing(connect_readonly(db_path)) as conn:
        assert list_accounts(conn) == [account]
        assert list_transactions(conn).total == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM accounts")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            create_account(conn, name="New", account_type=AccountType.OTHER, currency="CAD")


def test_readonly_connection_does_not_create_a_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"

    with pytest.raises(sqlite3.OperationalError, match="unable to open"):
        connect_readonly(path)
    assert not path.exists()


def test_readonly_connection_requires_a_migrated_database(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE unrelated (x INTEGER)")

    with pytest.raises(SchemaVersionError, match="connect\\(\\) first"):
        connect_readonly(db_path)


def test_readonly_connection_works_with_spaces_in_the_path(tmp_path: Path) -> None:
    path = tmp_path / "My Data" / "monelyth.db"
    path.parent.mkdir()
    connect(path).close()

    with closing(connect_readonly(path)) as conn:
        assert count_rows(conn, "categories") > 0


def _delete_accounts_then_fail(conn: sqlite3.Connection, message: str) -> None:
    with atomic(conn):
        conn.execute("DELETE FROM accounts")
        raise RuntimeError(message)


def _delete_accounts_in_inner_block_then_fail(conn: sqlite3.Connection) -> None:
    with atomic(conn):
        with atomic(conn):
            conn.execute("DELETE FROM accounts")
        raise RuntimeError("outer")


def test_atomic_commits_on_success(db: sqlite3.Connection, account: Account) -> None:
    with atomic(db):
        db.execute("DELETE FROM accounts")

    assert not db.in_transaction
    assert count_rows(db, "accounts") == 0


def test_atomic_rolls_back_on_error(db: sqlite3.Connection, account: Account) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        _delete_accounts_then_fail(db, "boom")

    assert not db.in_transaction
    assert count_rows(db, "accounts") == 1


def test_nested_atomic_undoes_only_the_failed_inner_block(
    db: sqlite3.Connection, account: Account
) -> None:
    with atomic(db):
        db.execute("UPDATE accounts SET name = 'Renamed'")
        with pytest.raises(RuntimeError, match="inner"):
            _delete_accounts_then_fail(db, "inner")
        assert db.in_transaction

    assert [a.name for a in list_accounts(db)] == ["Renamed"]


def test_outer_failure_undoes_a_committed_inner_block(
    db: sqlite3.Connection, account: Account
) -> None:
    with pytest.raises(RuntimeError, match="outer"):
        _delete_accounts_in_inner_block_then_fail(db)

    assert count_rows(db, "accounts") == 1


def test_read_snapshot_ignores_writes_from_other_connections(
    db_path: Path, db: sqlite3.Connection, account: Account
) -> None:
    with closing(connect(db_path)) as writer, read_snapshot(db):
        assert count_rows(db, "accounts") == 1
        writer.execute("DELETE FROM accounts")
        assert count_rows(db, "accounts") == 1

    assert count_rows(db, "accounts") == 0
