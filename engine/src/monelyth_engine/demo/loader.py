"""Fill an empty Monelyth with demo accounts, so someone can explore before importing anything.

The demo statements go through :func:`~monelyth_engine.services.importing.commit_import`, the
same path as a statement the user uploads, so what the demo shows is what a real import does.
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass
from typing import Final

from monelyth_engine.db.accounts import create_account, list_accounts
from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.errors import DuplicateImportError
from monelyth_engine.db.models import Account, AccountType
from monelyth_engine.demo.generator import Month, generate
from monelyth_engine.demo.statements import (
    CARD_CSV_LAYOUT,
    CHECKING_CSV_LAYOUT,
    card_csv,
    checking_csv,
)
from monelyth_engine.ingest.csv_statement import CsvLayout
from monelyth_engine.services.importing import ImportOutcome, StatementFile, commit_import

CHECKING_NAME: Final = "Demo Checking"
CARD_NAME: Final = "Demo Visa"
DEMO_ACCOUNT_NAMES: Final = (CHECKING_NAME, CARD_NAME)


class DemoDataExistsError(ValueError):
    """The demo accounts were added before. The message is shown to the user."""


@dataclass(frozen=True, slots=True)
class DemoImport:
    account: Account
    outcome: ImportOutcome


@dataclass(frozen=True, slots=True)
class DemoData:
    imports: tuple[DemoImport, ...]
    """The checking account first, then the card, each with what its statement added."""


@dataclass(frozen=True, slots=True)
class _Statement:
    account_name: str
    type: AccountType
    slug: str
    """Names the file, e.g. ``monelyth-demo-visa-2026-10-17.csv``."""
    text: str
    layout: CsvLayout


def add_demo_data(conn: sqlite3.Connection, *, currency: str, today: datetime.date) -> DemoData:
    """Create the demo checking account and card, and import a year of statements into them.

    The year is the twelve months ending with ``today``'s month, cut off at ``today`` as a
    statement downloaded that day would be. Everything is added together or not at all.

    Args:
        currency: ISO 4217 code for both accounts, e.g. ``CAD``.

    Raises:
        DemoDataExistsError: if an account already has one of the demo names.
        ValueError: if ``currency`` is not an upper-case three-letter code.
    """
    dataset = generate(Month.of(today)).through(today)
    statements = (
        _Statement(
            CHECKING_NAME,
            AccountType.CHECKING,
            "checking",
            checking_csv(dataset),
            CHECKING_CSV_LAYOUT,
        ),
        _Statement(CARD_NAME, AccountType.CREDIT_CARD, "visa", card_csv(dataset), CARD_CSV_LAYOUT),
    )
    imports: list[DemoImport] = []
    with atomic(conn):
        _refuse_existing_demo(conn)
        for statement in statements:
            account = create_account(
                conn, name=statement.account_name, account_type=statement.type, currency=currency
            )
            # The date makes each name distinct and tells the user which day the data ends.
            file = StatementFile(
                name=f"monelyth-demo-{statement.slug}-{today}.csv", data=statement.text.encode()
            )
            try:
                outcome = commit_import(
                    conn, account_id=account.id, file=file, layout=statement.layout
                )
            except DuplicateImportError:
                # Today's demo statement is already stored, under accounts renamed since.
                raise DemoDataExistsError(
                    "Today's demo data has already been added to Monelyth."
                ) from None
            imports.append(DemoImport(account=account, outcome=outcome))
    return DemoData(imports=tuple(imports))


def _refuse_existing_demo(conn: sqlite3.Connection) -> None:
    demo_names = {name.casefold() for name in DEMO_ACCOUNT_NAMES}
    if any(account.name.casefold() in demo_names for account in list_accounts(conn)):
        raise DemoDataExistsError(
            f"The demo data has already been added: look for {CHECKING_NAME} and {CARD_NAME} "
            "in your accounts."
        )
