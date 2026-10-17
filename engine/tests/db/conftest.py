from __future__ import annotations

import datetime
import hashlib
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from monelyth_engine.db.accounts import create_account
from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.connection import connect
from monelyth_engine.db.imports import record_import
from monelyth_engine.db.models import Account, AccountType, InsertResult, NewTransaction
from monelyth_engine.db.transactions import insert_transactions
from monelyth_engine.ingest.models import RawTransaction, StatementFormat

ImportStatement = Callable[..., InsertResult]


def raw(
    day: int,
    amount_cents: int,
    description: str,
    external_id: str | None = None,
    *,
    month: int = 9,
) -> RawTransaction:
    return RawTransaction(datetime.date(2026, month, day), amount_cents, description, external_id)


def sha256_of(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    assert table.isidentifier()
    count: int = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    return count


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "monelyth.db"


@pytest.fixture
def db(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    yield conn
    conn.close()


@pytest.fixture
def account(db: sqlite3.Connection) -> Account:
    return create_account(
        db, name="Main Checking", account_type=AccountType.CHECKING, currency="CAD"
    )


@pytest.fixture
def import_statement(db: sqlite3.Connection, account: Account) -> ImportStatement:
    """Record a file and store its rows in one unit, the way the import service will."""

    def run(
        rows: Sequence[RawTransaction],
        *,
        file_label: str,
        account_id: int = account.id,
        merchants: Sequence[str | None] | None = None,
    ) -> InsertResult:
        names = merchants if merchants is not None else [None] * len(rows)
        with atomic(db):
            record = record_import(
                db,
                account_id=account_id,
                file_name=f"{file_label}.csv",
                file_sha256=sha256_of(file_label),
                statement_format=StatementFormat.CSV,
                row_count=len(rows),
            )
            return insert_transactions(
                db,
                account_id=account_id,
                import_id=record.id,
                items=[NewTransaction(row, name) for row, name in zip(rows, names, strict=True)],
            )

    return run
