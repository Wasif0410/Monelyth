"""Opening the database.

Every connection is configured the same way:

- **Autocommit mode.** Python's default implicitly opens transactions on some statements and
  not others; here nothing is grouped unless the code uses :func:`~monelyth_engine.db.atomic`.
- **Rows are** :class:`sqlite3.Row`, read by column name. Repository functions turn them into
  the typed dataclasses in :mod:`monelyth_engine.db.models`, so rows never leave this package.
- **A ``casefold`` SQL function**, because SQLite's own ``lower()`` and ``LIKE`` only fold
  ASCII and would miss "CAFÉ" when searching for "café".
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Final

from monelyth_engine.db.errors import SchemaVersionError
from monelyth_engine.db.schema import ensure_not_newer, latest_version, migrate, schema_version

BUSY_TIMEOUT_SECONDS: Final = 5.0
"""How long a connection waits for another one's write lock before giving up."""

logger = logging.getLogger(__name__)


def connect(path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open the database at ``path`` for reading and writing, creating and migrating it.

    The parent folder must already exist.

    Args:
        check_same_thread: keep Python's guard that only the creating thread may use the
            connection. Pass ``False`` only when the connection may move between threads but
            is never used by two at once (e.g. one web request whose setup and handler run on
            different worker threads).

    Raises:
        SchemaVersionError: if the file was created by a newer version of Monelyth. The file
            is left untouched.
        sqlite3.Error: if the file cannot be opened or is not a database.
    """
    conn = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_SECONDS,
        autocommit=True,
        check_same_thread=check_same_thread,
    )
    try:
        _configure(conn)
        # Check before anything that writes: switching to WAL changes the file header.
        ensure_not_newer(conn)
        _enable_wal(conn, path)
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Open an existing, already migrated database so that no statement can change it.

    SQLite enforces this itself (``mode=ro``), so it holds even for SQL the engine did not
    write, such as queries driven by the chat assistant.

    Raises:
        SchemaVersionError: if the database is not at this build's schema version.
        sqlite3.Error: if the file does not exist or cannot be opened.
    """
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SECONDS, autocommit=True)
    try:
        _configure(conn)
        if ensure_not_newer(conn) != latest_version():
            raise SchemaVersionError(
                f"The database is at schema version {schema_version(conn)} but this build "
                f"needs {latest_version()}; open it with connect() first to upgrade it."
            )
    except BaseException:
        conn.close()
        raise
    return conn


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.create_function("casefold", 1, _casefold, deterministic=True)
    # Off by default in SQLite and set per connection; without it REFERENCES is ignored.
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("This SQLite build does not support foreign keys")


def _enable_wal(conn: sqlite3.Connection, path: Path) -> None:
    """Let readers and the writer work at the same time (the mode is stored in the file)."""
    mode: str = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if mode.lower() != "wal":
        # Happens on file systems without shared memory, e.g. some network drives. The
        # database still works correctly, just with less concurrency.
        logger.warning("Could not enable WAL for %s; journal mode is %r", path, mode)


def _casefold(value: str | None) -> str | None:
    return None if value is None else value.casefold()
