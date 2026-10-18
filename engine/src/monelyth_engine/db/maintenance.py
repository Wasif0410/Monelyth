"""Whole-database operations: counting, copying and erasing everything the user stored."""

from __future__ import annotations

import datetime
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.schema import migrate

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DataCounts:
    accounts: int
    transactions: int


@dataclass(frozen=True, slots=True)
class ExportedTransaction:
    """One transaction as it appears in the CSV export, with names in place of IDs."""

    posted_date: datetime.date
    account: str
    description: str
    merchant: str | None
    category: str | None
    amount_cents: int
    currency: str


def count_data(conn: sqlite3.Connection) -> DataCounts:
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM accounts), (SELECT COUNT(*) FROM transactions)"
    ).fetchone()
    return DataCounts(accounts=row[0], transactions=row[1])


def backup_database(conn: sqlite3.Connection, target: Path) -> None:
    """Write a consistent copy of the database to ``target``, which must not exist yet.

    Uses SQLite's online backup API, which copies one snapshot even while other connections
    write; copying the file itself could catch it, or its write-ahead log, mid-write. The copy
    is a single self-contained file (no ``-wal`` file next to it).

    Raises:
        FileExistsError: if ``target`` already exists.
        sqlite3.Error: if the copy can't be written, e.g. because the disk is full.
    """
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    with closing(sqlite3.connect(target, autocommit=True)) as copy:
        conn.backup(copy)
        copy.execute("PRAGMA journal_mode = DELETE")


def exported_transactions(conn: sqlite3.Connection) -> Iterator[ExportedTransaction]:
    """Every transaction, oldest first, with its account and category names.

    Takes a plain connection too (such as one to a backup copy), so it reads columns by
    position rather than relying on the engine's row factory.
    """
    cursor = conn.execute(
        "SELECT t.posted_date, a.name, t.description_raw, t.merchant, c.name, "
        "t.amount_cents, a.currency "
        "FROM transactions AS t "
        "JOIN accounts AS a ON a.id = t.account_id "
        "LEFT JOIN categories AS c ON c.id = t.category_id "
        "ORDER BY t.posted_date, t.id"
    )
    for posted_date, account, description, merchant, category, amount_cents, currency in cursor:
        yield ExportedTransaction(
            posted_date=datetime.date.fromisoformat(posted_date),
            account=account,
            description=description,
            merchant=merchant,
            category=category,
            amount_cents=amount_cents,
            currency=currency,
        )


def erase_all_data(conn: sqlite3.Connection) -> DataCounts:
    """Delete everything the user stored and restore the rows a new database starts with.

    Every table is emptied in one all-or-nothing step, then refilled with the seed rows (such
    as the default categories) of a freshly migrated database, so the result is exactly what
    a first launch creates. Deleted content is overwritten on disk rather than just marked
    free, and the file is compacted afterwards when no other connection is busy with it.

    Returns how many accounts and transactions were deleted.
    """
    seeds = _fresh_seed_rows()
    conn.execute("PRAGMA secure_delete = ON")
    with atomic(conn):
        deleted = count_data(conn)
        # Checked at commit instead of per statement, so tables can be emptied in any order.
        conn.execute("PRAGMA defer_foreign_keys = ON")
        for table in _tables(conn):
            # Table names come from sqlite_master and are quoted; values are never interpolated.
            conn.execute(f"DELETE FROM {_quote(table)}")  # noqa: S608
        for table, (columns, rows) in seeds.items():
            placeholders = ", ".join("?" for _ in columns)
            conn.executemany(
                f"INSERT INTO {_quote(table)} ({', '.join(map(_quote, columns))}) "  # noqa: S608
                f"VALUES ({placeholders})",
                rows,
            )
    _compact(conn)
    return deleted


def _fresh_seed_rows() -> dict[str, tuple[tuple[str, ...], list[tuple[object, ...]]]]:
    """The rows each table holds right after the migrations run on an empty database."""
    seeds: dict[str, tuple[tuple[str, ...], list[tuple[object, ...]]]] = {}
    with closing(sqlite3.connect(":memory:", autocommit=True)) as fresh:
        migrate(fresh)
        for table in _tables(fresh):
            cursor = fresh.execute(f"SELECT * FROM {_quote(table)}")  # noqa: S608
            rows: list[tuple[object, ...]] = cursor.fetchall()
            if rows:
                seeds[table] = (tuple(column[0] for column in cursor.description), rows)
    return seeds


def _tables(conn: sqlite3.Connection) -> list[str]:
    """The schema's own tables, leaving out SQLite's internal ones."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' "
        "ESCAPE '\\' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _compact(conn: sqlite3.Connection) -> None:
    """Shrink the file and empty the write-ahead log. Skipped if another connection is busy:
    the data is already gone, this only reclaims space."""
    try:
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as error:
        logger.warning("Could not compact the database after erasing it: %s", error)
