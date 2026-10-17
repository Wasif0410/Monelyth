"""Explicit transaction scopes.

Connections are opened in autocommit mode, so nothing is grouped into a transaction unless
the code says so. Every write that touches more than one row goes through :func:`atomic`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Final

_SAVEPOINT: Final = "monelyth_nested"


@contextmanager
def atomic(conn: sqlite3.Connection) -> Generator[None]:
    """Commit everything inside the block together, or roll all of it back on any error.

    Scopes nest: inside an outer scope this uses a savepoint, so a failing inner block undoes
    only its own work while the outer block decides whether the rest commits. That lets callers
    combine repository functions (for example recording an import and inserting its
    transactions) into one all-or-nothing unit.

    The outermost scope uses ``BEGIN IMMEDIATE``, which takes the write lock up front. A plain
    ``BEGIN`` would start as a reader and could fail with "database is locked" when it later
    tries to write, without the busy timeout ever applying.
    """
    if conn.in_transaction:
        with _scope(conn, f"SAVEPOINT {_SAVEPOINT}", f"RELEASE {_SAVEPOINT}", _rollback_savepoint):
            yield
    else:
        with _scope(conn, "BEGIN IMMEDIATE", "COMMIT", _rollback):
            yield


@contextmanager
def read_snapshot(conn: sqlite3.Connection) -> Generator[None]:
    """Run several reads against one consistent view of the database.

    Without this, a write from another connection could land between two queries, e.g.
    between fetching a page of rows and counting the total. Works on read-only connections.
    Inside an existing transaction the reads already share its view, so this does nothing.
    """
    if conn.in_transaction:
        yield
    else:
        with _scope(conn, "BEGIN DEFERRED", "COMMIT", _rollback):
            yield


@contextmanager
def _scope(
    conn: sqlite3.Connection,
    begin: str,
    finish: str,
    rollback: Callable[[sqlite3.Connection], None],
) -> Generator[None]:
    conn.execute(begin)
    try:
        yield
        conn.execute(finish)
    except BaseException:
        rollback(conn)
        raise


def _rollback(conn: sqlite3.Connection) -> None:
    # Some errors (e.g. a full disk) make SQLite roll back on its own; rolling back again
    # would raise and hide the original error.
    if conn.in_transaction:
        conn.execute("ROLLBACK")


def _rollback_savepoint(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.execute(f"ROLLBACK TO {_SAVEPOINT}")
        conn.execute(f"RELEASE {_SAVEPOINT}")
