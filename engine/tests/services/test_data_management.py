from __future__ import annotations

import datetime
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from monelyth_engine.db.connection import connect
from monelyth_engine.services import data_management
from monelyth_engine.services.data_management import (
    ExportError,
    decimal_amount,
    export_everything,
)

NOW = datetime.datetime(2026, 10, 17, 9, 5, 7, tzinfo=datetime.UTC)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(tmp_path / "monelyth.db")
    yield conn
    conn.close()


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "exports"
    folder.mkdir()
    return folder


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, "0.00"),
        (5, "0.05"),
        (-5, "-0.05"),
        (-1_299, "-12.99"),
        (100, "1.00"),
        (123_456_789, "1234567.89"),
        (-(2**63), "-92233720368547758.08"),
    ],
)
def test_decimal_amount(cents: int, expected: str) -> None:
    assert decimal_amount(cents) == expected


def test_export_folder_is_named_after_the_local_time(
    db: sqlite3.Connection, export_dir: Path
) -> None:
    result = export_everything(db, str(export_dir), now=NOW)

    assert result.folder == export_dir / "Monelyth export 2026-10-17 090507"
    assert result.transaction_count == 0


def test_a_second_export_in_the_same_second_gets_a_new_folder(
    db: sqlite3.Connection, export_dir: Path
) -> None:
    first = export_everything(db, str(export_dir), now=NOW).folder
    second = export_everything(db, str(export_dir), now=NOW).folder
    third = export_everything(db, str(export_dir), now=NOW).folder

    assert [first.name, second.name, third.name] == [
        "Monelyth export 2026-10-17 090507",
        "Monelyth export 2026-10-17 090507 (2)",
        "Monelyth export 2026-10-17 090507 (3)",
    ]


def test_an_unwritable_folder_is_rejected(
    db: sqlite3.Connection, export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Access is denied", str(self))

    monkeypatch.setattr(Path, "mkdir", refuse)

    with pytest.raises(ExportError, match=r"can't create files in .*exports"):
        export_everything(db, str(export_dir), now=NOW)


def test_a_failed_export_leaves_nothing_behind(
    db: sqlite3.Connection, export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disk_full(conn: sqlite3.Connection, target: Path) -> None:
        target.write_bytes(b"partial")
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(data_management, "backup_database", disk_full)

    with pytest.raises(ExportError, match=r"could not be written .*: database or disk is full"):
        export_everything(db, str(export_dir), now=NOW)

    assert list(export_dir.iterdir()) == []
