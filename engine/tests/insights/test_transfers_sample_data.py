"""Transfer detection on the committed demo statements, checked against ``labels.csv``."""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from monelyth_engine.db.accounts import create_account
from monelyth_engine.db.connection import connect
from monelyth_engine.db.models import AccountType
from monelyth_engine.demo.statements import CARD_CSV_LAYOUT, CHECKING_CSV_LAYOUT
from monelyth_engine.ingest.csv_statement import CsvLayout
from monelyth_engine.insights.transfers import link_transfers
from monelyth_engine.services.importing import StatementFile, commit_import

SAMPLE_DATA: Final = Path(__file__).resolve().parents[3] / "sample-data"

type Row = tuple[str, str, str, int]
"""account type, posted date, description, amount in cents: how labels.csv names a row."""


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(tmp_path / "monelyth.db")
    yield conn
    conn.close()


def _import(
    conn: sqlite3.Connection, account_type: AccountType, file_name: str, layout: CsvLayout
) -> None:
    account = create_account(
        conn, name=file_name, account_type=account_type, currency="CAD", institution="Demo Bank"
    )
    file = StatementFile(name=file_name, data=(SAMPLE_DATA / file_name).read_bytes())
    commit_import(conn, account_id=account.id, file=file, layout=layout)


def _labelled_transfers() -> list[Row]:
    with (SAMPLE_DATA / "labels.csv").open(encoding="utf-8", newline="") as file:
        return [
            (row["account"], row["date"], row["description"], int(row["amount_cents"]))
            for row in csv.DictReader(file)
            if row["category"] == "Transfers"
        ]


def _linked(conn: sqlite3.Connection) -> list[Row]:
    rows = conn.execute(
        "SELECT a.type, t.posted_date, t.description_raw, t.amount_cents "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.transfer_group IS NOT NULL"
    ).fetchall()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def test_every_card_payment_and_nothing_else_is_linked(db: sqlite3.Connection) -> None:
    _import(db, AccountType.CHECKING, "demo-checking.csv", CHECKING_CSV_LAYOUT)
    _import(db, AccountType.CREDIT_CARD, "demo-credit-card.csv", CARD_CSV_LAYOUT)
    expected = _labelled_transfers()
    assert len(expected) == 22, "labels.csv holds 11 card payments, each with two sides"

    pairs = link_transfers(db)

    linked = _linked(db)
    true_positives = len(set(linked) & set(expected))
    precision = true_positives / len(linked)
    recall = true_positives / len(expected)
    assert (precision, recall) == (1.0, 1.0)
    assert pairs == 11
    assert sorted(linked) == sorted(expected)
    # Each pair joins one side from each account.
    sides = db.execute(
        "SELECT GROUP_CONCAT(a.type) FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.transfer_group IS NOT NULL GROUP BY t.transfer_group"
    ).fetchall()
    assert sorted(set(row[0].split(",")) for row in sides) == [{"checking", "credit_card"}] * 11
