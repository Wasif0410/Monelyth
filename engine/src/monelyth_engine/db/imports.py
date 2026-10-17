"""One record per imported statement file, used to reject the same file a second time."""

from __future__ import annotations

import datetime
import re
import sqlite3
from typing import Final

from monelyth_engine.db.accounts import get_account
from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.errors import DuplicateImportError
from monelyth_engine.db.models import ImportRecord
from monelyth_engine.ingest.models import StatementFormat

_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")


def find_import(conn: sqlite3.Connection, file_sha256: str) -> ImportRecord | None:
    """The earlier import of the file with this hash, if any (e.g. to warn during a preview)."""
    row = conn.execute(
        "SELECT id, account_id, file_name, file_sha256, format, imported_at, row_count "
        "FROM imports WHERE file_sha256 = ?",
        (file_sha256,),
    ).fetchone()
    return None if row is None else _to_import(row)


def record_import(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    file_name: str,
    file_sha256: str,
    statement_format: StatementFormat,
    row_count: int,
    imported_at: datetime.datetime | None = None,
) -> ImportRecord:
    """Record that a file is being imported into an account.

    Call this and :func:`~monelyth_engine.db.transactions.insert_transactions` inside one
    :func:`~monelyth_engine.db.atomic.atomic` block, so a failure part-way through leaves
    neither the record nor any of its transactions behind (and the file can be retried).

    Args:
        file_sha256: lower-case hex SHA-256 of the file's bytes.
        row_count: how many transactions the file contains.
        imported_at: defaults to now; must be timezone-aware. Stored in UTC.

    Raises:
        DuplicateImportError: if a file with the same hash was imported before.
        NotFoundError: if the account does not exist.
        ValueError: if an argument is malformed.
    """
    if not file_name.strip():
        raise ValueError("file_name must not be empty")
    if not _SHA256_HEX.fullmatch(file_sha256):
        raise ValueError("file_sha256 must be 64 lower-case hex characters")
    if row_count < 0:
        raise ValueError("row_count must not be negative")
    if imported_at is None:
        imported_at = datetime.datetime.now(datetime.UTC)
    elif imported_at.utcoffset() is None:
        raise ValueError("imported_at must be timezone-aware")

    with atomic(conn):
        get_account(conn, account_id)
        existing = find_import(conn, file_sha256)
        if existing is not None:
            raise DuplicateImportError(existing)
        row = conn.execute(
            "INSERT INTO imports "
            "(account_id, file_name, file_sha256, format, imported_at, row_count) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "RETURNING id, account_id, file_name, file_sha256, format, imported_at, row_count",
            (
                account_id,
                file_name,
                file_sha256,
                statement_format.value,
                imported_at.astimezone(datetime.UTC).isoformat(timespec="seconds"),
                row_count,
            ),
        ).fetchone()
    return _to_import(row)


def _to_import(row: sqlite3.Row) -> ImportRecord:
    return ImportRecord(
        id=row["id"],
        account_id=row["account_id"],
        file_name=row["file_name"],
        file_sha256=row["file_sha256"],
        format=StatementFormat(row["format"]),
        imported_at=datetime.datetime.fromisoformat(row["imported_at"]),
        row_count=row["row_count"],
    )
