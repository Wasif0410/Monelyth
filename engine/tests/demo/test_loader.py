from __future__ import annotations

import datetime
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from monelyth_engine.db.accounts import create_account, list_accounts
from monelyth_engine.db.connection import connect
from monelyth_engine.db.models import AccountType
from monelyth_engine.demo import DemoDataExistsError, Month, add_demo_data, generate
from monelyth_engine.demo import loader as loader_module
from monelyth_engine.ingest.csv_statement import CsvLayout
from monelyth_engine.services.importing import ImportOutcome, StatementFile

TODAY: Final = datetime.date(2026, 10, 17)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(tmp_path / "monelyth.db")
    yield conn
    conn.close()


def _count(conn: sqlite3.Connection, table: str) -> int:
    assert table.isidentifier()
    count: int = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    return count


def test_adds_both_accounts_with_their_statements(db: sqlite3.Connection) -> None:
    data = add_demo_data(db, currency="USD", today=TODAY)

    expected = generate(Month.of(TODAY)).through(TODAY)
    checking, card = data.imports
    assert (checking.account.name, checking.account.type) == ("Demo Checking", "checking")
    assert (card.account.name, card.account.type) == ("Demo Visa", "credit_card")
    assert {checking.account.currency, card.account.currency} == {"USD"}
    assert checking.outcome.added == len(expected.checking)
    assert card.outcome.added == len(expected.card)
    assert checking.outcome.skipped_duplicates == card.outcome.skipped_duplicates == 0
    assert checking.outcome.record.file_name == "monelyth-demo-checking-2026-10-17.csv"
    assert card.outcome.record.file_name == "monelyth-demo-visa-2026-10-17.csv"
    assert _count(db, "transactions") == len(expected.checking) + len(expected.card)
    latest: str = db.execute("SELECT MAX(posted_date) FROM transactions").fetchone()[0]
    assert latest <= TODAY.isoformat()


def test_existing_accounts_of_the_user_do_not_block_it(db: sqlite3.Connection) -> None:
    create_account(db, name="Main Checking", account_type=AccountType.CHECKING, currency="CAD")

    add_demo_data(db, currency="CAD", today=TODAY)

    assert [account.name for account in list_accounts(db)] == [
        "Main Checking",
        "Demo Checking",
        "Demo Visa",
    ]


@pytest.mark.parametrize("name", ["Demo Checking", "demo visa"])
def test_refused_when_a_demo_account_exists(db: sqlite3.Connection, name: str) -> None:
    create_account(db, name=name, account_type=AccountType.OTHER, currency="CAD")

    with pytest.raises(DemoDataExistsError, match="already been added"):
        add_demo_data(db, currency="CAD", today=TODAY)

    assert len(list_accounts(db)) == 1
    assert _count(db, "imports") == 0


def test_refused_when_the_same_days_statements_were_imported(db: sqlite3.Connection) -> None:
    add_demo_data(db, currency="CAD", today=TODAY)
    db.execute("UPDATE accounts SET name = 'Renamed ' || id")

    with pytest.raises(DemoDataExistsError, match="already been added"):
        add_demo_data(db, currency="CAD", today=TODAY)

    assert len(list_accounts(db)) == 2


def test_a_failure_part_way_leaves_nothing_behind(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_commit = loader_module.commit_import
    calls = 0

    def fail_on_the_card(
        conn: sqlite3.Connection,
        *,
        account_id: int,
        file: StatementFile,
        layout: CsvLayout | None,
    ) -> ImportOutcome:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("disk full")
        return real_commit(conn, account_id=account_id, file=file, layout=layout)

    monkeypatch.setattr(loader_module, "commit_import", fail_on_the_card)

    with pytest.raises(RuntimeError, match="disk full"):
        add_demo_data(db, currency="CAD", today=TODAY)

    assert calls == 2
    for table in ("accounts", "imports", "transactions", "csv_profiles"):
        assert _count(db, table) == 0, table
    assert not db.in_transaction
