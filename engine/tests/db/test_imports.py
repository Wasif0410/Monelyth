from __future__ import annotations

import datetime
import sqlite3
from typing import Any

import pytest

from monelyth_engine.db.errors import DuplicateImportError, NotFoundError
from monelyth_engine.db.imports import find_import, record_import
from monelyth_engine.db.models import Account
from monelyth_engine.ingest.models import StatementFormat
from tests.db.conftest import count_rows, sha256_of

IMPORTED_AT = datetime.datetime(
    2026, 10, 1, 9, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=-4))
)


def _record(conn: sqlite3.Connection, account_id: int, label: str = "sept") -> int:
    return record_import(
        conn,
        account_id=account_id,
        file_name=f"{label}.ofx",
        file_sha256=sha256_of(label),
        statement_format=StatementFormat.OFX,
        row_count=12,
        imported_at=IMPORTED_AT,
    ).id


def test_record_import_stores_the_file_in_utc(db: sqlite3.Connection, account: Account) -> None:
    record = record_import(
        db,
        account_id=account.id,
        file_name="sept.ofx",
        file_sha256=sha256_of("sept"),
        statement_format=StatementFormat.OFX,
        row_count=12,
        imported_at=IMPORTED_AT,
    )

    assert record.account_id == account.id
    assert record.format is StatementFormat.OFX
    assert record.row_count == 12
    assert record.imported_at == IMPORTED_AT
    assert record.imported_at.utcoffset() == datetime.timedelta(0)
    assert find_import(db, sha256_of("sept")) == record


def test_imported_at_defaults_to_now(db: sqlite3.Connection, account: Account) -> None:
    before = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    record = record_import(
        db,
        account_id=account.id,
        file_name="sept.csv",
        file_sha256=sha256_of("sept"),
        statement_format=StatementFormat.CSV,
        row_count=0,
    )

    assert before <= record.imported_at <= datetime.datetime.now(datetime.UTC)


def test_same_file_twice_is_rejected(db: sqlite3.Connection, account: Account) -> None:
    first_id = _record(db, account.id)

    with pytest.raises(DuplicateImportError, match="already imported on 2026-") as excinfo:
        _record(db, account.id)

    assert excinfo.value.existing.id == first_id
    assert "'sept.ofx'" in str(excinfo.value)
    assert count_rows(db, "imports") == 1


def test_find_import_returns_none_for_a_new_file(db: sqlite3.Connection) -> None:
    assert find_import(db, sha256_of("never seen")) is None


def test_unknown_account_is_rejected(db: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="Account 7"):
        _record(db, 7)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"file_name": " "}, "file_name"),
        ({"file_sha256": "ABC"}, "64 lower-case hex"),
        ({"file_sha256": sha256_of("x").upper()}, "64 lower-case hex"),
        ({"row_count": -1}, "row_count"),
        ({"imported_at": datetime.datetime(2026, 10, 1)}, "timezone-aware"),
    ],
)
def test_malformed_arguments_are_rejected(
    db: sqlite3.Connection, account: Account, overrides: dict[str, Any], message: str
) -> None:
    arguments: dict[str, Any] = {
        "file_name": "sept.csv",
        "file_sha256": sha256_of("sept"),
        "row_count": 1,
        "imported_at": IMPORTED_AT,
    } | overrides

    with pytest.raises(ValueError, match=message):
        record_import(db, account_id=account.id, statement_format=StatementFormat.CSV, **arguments)
    assert count_rows(db, "imports") == 0
