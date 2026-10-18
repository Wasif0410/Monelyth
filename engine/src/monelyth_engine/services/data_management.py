"""Taking all of the user's data with them, and finding out where it lives.

An export is a new folder holding a consistent copy of the database, a CSV of every
transaction for spreadsheets, and a README explaining both. It is written next to nothing
else, so a failed export is removed instead of leaving half a folder behind.
"""

from __future__ import annotations

import csv
import datetime
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from monelyth_engine import __version__
from monelyth_engine.db.maintenance import (
    DataCounts,
    backup_database,
    count_data,
    exported_transactions,
)

DATABASE_COPY_NAME: Final = "monelyth.db"
TRANSACTIONS_CSV_NAME: Final = "transactions.csv"
README_NAME: Final = "README.txt"
CSV_HEADER: Final = ("Date", "Account", "Description", "Merchant", "Category", "Amount", "Currency")

_MAX_FOLDER_ATTEMPTS: Final = 100
_FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")
"""Spreadsheets run a cell starting with one of these as a formula. Bank descriptions are
partly written by merchants, so text cells that start this way are prefixed with ``'``."""


class ExportError(ValueError):
    """The export can't be written as asked. The message is shown to the user."""


@dataclass(frozen=True, slots=True)
class SystemInfo:
    engine_version: str
    data_folder: Path
    database_path: Path
    database_size_bytes: int
    """The database file plus its write-ahead log, i.e. the space the data takes on disk."""
    counts: DataCounts


@dataclass(frozen=True, slots=True)
class ExportResult:
    folder: Path
    transaction_count: int


def system_info(conn: sqlite3.Connection, database_path: Path) -> SystemInfo:
    wal = database_path.with_name(f"{database_path.name}-wal")
    return SystemInfo(
        engine_version=__version__,
        data_folder=database_path.parent,
        database_path=database_path,
        database_size_bytes=_file_size(database_path) + _file_size(wal),
        counts=count_data(conn),
    )


def export_everything(
    conn: sqlite3.Connection, folder: str, *, now: datetime.datetime
) -> ExportResult:
    """Write a new ``Monelyth export <date> <time>`` folder inside ``folder``.

    The CSV is made from the database copy rather than the live database, so the two always
    hold exactly the same transactions even if an import finishes during the export.

    Args:
        folder: an existing folder, as a full path.
        now: the local time to name the export folder after.

    Raises:
        ExportError: if ``folder`` is not a full path to an existing folder Monelyth can write
            to, or the files can't be written (e.g. because the disk is full).
    """
    parent = _validate_folder(folder)
    target = _create_export_folder(parent, f"Monelyth export {now:%Y-%m-%d %H%M%S}")
    try:
        database_copy = target / DATABASE_COPY_NAME
        backup_database(conn, database_copy)
        with closing(sqlite3.connect(database_copy, autocommit=True)) as copy:
            count = _write_transactions_csv(copy, target / TRANSACTIONS_CSV_NAME)
        _write_readme(target / README_NAME, now=now, transaction_count=count)
    except (OSError, sqlite3.Error) as error:
        shutil.rmtree(target, ignore_errors=True)
        raise ExportError(f"The export could not be written to {parent}: {error}") from error
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return ExportResult(folder=target, transaction_count=count)


def decimal_amount(cents: int) -> str:
    """``-1299`` → ``"-12.99"``, exact for any amount (no floating point involved)."""
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def _validate_folder(folder: str) -> Path:
    path = Path(folder)
    if not path.is_absolute():
        raise ExportError("Choose the export folder by its full path.")
    if not path.exists():
        raise ExportError(f"The folder {folder} doesn't exist.")
    if not path.is_dir():
        raise ExportError(f"{folder} is a file, not a folder.")
    return path


def _create_export_folder(parent: Path, name: str) -> Path:
    """Create a new folder, adding " (2)", " (3)", ... if one with that name already exists."""
    for attempt in range(1, _MAX_FOLDER_ATTEMPTS + 1):
        candidate = parent / (name if attempt == 1 else f"{name} ({attempt})")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        except OSError as error:
            raise ExportError(
                f"Monelyth can't create files in {parent}. Choose a folder you can write to."
            ) from error
        return candidate
    raise ExportError(f"{parent} already has too many exports named {name!r}.")


def _write_transactions_csv(conn: sqlite3.Connection, path: Path) -> int:
    count = 0
    # UTF-8 with a byte order mark, so Excel reads accented names correctly; csv's own
    # quoting and "\r\n" line endings are what spreadsheets expect.
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(CSV_HEADER)
        for tx in exported_transactions(conn):
            writer.writerow(
                (
                    tx.posted_date.isoformat(),
                    _text_cell(tx.account),
                    _text_cell(tx.description),
                    _text_cell(tx.merchant),
                    _text_cell(tx.category),
                    decimal_amount(tx.amount_cents),
                    tx.currency,
                )
            )
            count += 1
    return count


def _text_cell(value: str | None) -> str:
    if value is None:
        return ""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def _write_readme(path: Path, *, now: datetime.datetime, transaction_count: int) -> None:
    noun = "transaction" if transaction_count == 1 else "transactions"
    path.write_text(
        f"""Monelyth export
Created {now:%Y-%m-%d %H:%M:%S} by Monelyth engine {__version__}.

{DATABASE_COPY_NAME}
    A complete copy of your Monelyth database: accounts, imports, transactions,
    categories and everything else. It is a standard SQLite 3 file that any SQLite
    tool can open, such as DB Browser for SQLite. Amounts are stored in cents.

{TRANSACTIONS_CSV_NAME}
    All {transaction_count} {noun}, oldest first, with account and category names,
    for Excel, Numbers or Google Sheets. Amounts are in the account's currency:
    negative is money out, positive is money in. Text that a spreadsheet would run
    as a formula (starting with =, +, -, or @) begins with an apostrophe.

These files were written only to this folder. Monelyth never sends your data anywhere.
""",
        encoding="utf-8",
    )


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0
