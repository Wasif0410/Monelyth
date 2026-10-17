"""Schema migrations, tracked with SQLite's built-in ``PRAGMA user_version`` counter.

Migrations are the numbered files in ``db/migrations/`` (``001_init.sql``, ``002_....sql``).
They are read with :mod:`importlib.resources`, so they load the same way from a source
checkout, an installed wheel or a PyInstaller bundle (which must include them as data files).

Rules for migration files: numbers start at 1 with no gaps, a file never changes once it has
shipped, and a file contains no ``BEGIN``/``COMMIT`` because the runner wraps each one in its
own transaction.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Final

from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.errors import SchemaVersionError

_MIGRATIONS_DIR: Final = "migrations"
_FILE_NAME: Final = re.compile(r"(?P<version>\d{3})_[a-z0-9_]+\.sql")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


@cache
def bundled_migrations() -> tuple[Migration, ...]:
    """The migrations shipped with this build, ordered by version.

    Raises:
        RuntimeError: if the files are misnamed, duplicated or have a gap in numbering. That is
            a packaging bug, so it fails loudly rather than leaving a half-built schema.
    """
    directory = resources.files(__package__) / _MIGRATIONS_DIR
    migrations: list[Migration] = []
    for entry in directory.iterdir():
        if not entry.name.endswith(".sql"):
            continue
        match = _FILE_NAME.fullmatch(entry.name)
        if match is None:
            raise RuntimeError(f"Migration file {entry.name!r} must be named like '001_init.sql'")
        migrations.append(
            Migration(int(match["version"]), entry.name, entry.read_text(encoding="utf-8"))
        )

    migrations.sort(key=lambda migration: migration.version)
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise RuntimeError(f"Migrations must be numbered 1, 2, 3, ... with no gaps; got {versions}")
    return tuple(migrations)


def latest_version() -> int:
    """The schema version this build creates and expects."""
    return len(bundled_migrations())


def schema_version(conn: sqlite3.Connection) -> int:
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return version


def ensure_not_newer(conn: sqlite3.Connection, latest: int | None = None) -> int:
    """Return the database's schema version, refusing one newer than this build understands.

    Opening such a file would mean writing to tables whose meaning this build does not know,
    so it is rejected before anything is written.

    Raises:
        SchemaVersionError: if the database was created by a newer version of the app.
    """
    current = schema_version(conn)
    if current > (latest_version() if latest is None else latest):
        raise SchemaVersionError(
            "This data was created by a newer version of Monelyth. "
            "Update Monelyth to open it; your data has not been changed."
        )
    return current


def migrate(conn: sqlite3.Connection, migrations: Sequence[Migration] | None = None) -> int:
    """Apply every migration newer than the database's version and return the final version.

    Each migration and its version bump commit together, so a failure leaves the database at
    the last migration that fully succeeded. Running this on an up-to-date database changes
    nothing.

    Args:
        migrations: defaults to :func:`bundled_migrations`; tests pass their own.

    Raises:
        SchemaVersionError: if the database is newer than the newest migration.
    """
    pending = bundled_migrations() if migrations is None else migrations
    latest = pending[-1].version if pending else 0
    if ensure_not_newer(conn, latest) == latest:
        return latest

    for migration in pending:
        with atomic(conn):
            # Re-read inside the write lock: another process may have migrated meanwhile.
            if schema_version(conn) >= migration.version:
                continue
            conn.executescript(migration.sql)
            # PRAGMA values cannot be bound as parameters; the version is an int we parsed.
            conn.execute(f"PRAGMA user_version = {migration.version:d}")
    return schema_version(conn)
