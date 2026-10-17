"""Bank accounts and cards."""

from __future__ import annotations

import re
import sqlite3
from typing import Final

from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.models import Account, AccountType

_CURRENCY_CODE: Final = re.compile(r"[A-Z]{3}")


def create_account(
    conn: sqlite3.Connection,
    *,
    name: str,
    account_type: AccountType,
    currency: str,
    institution: str | None = None,
) -> Account:
    """Add an account. Surrounding whitespace is trimmed from the name and institution.

    Raises:
        ValueError: if the name is blank or the currency is not an upper-case three-letter
            ISO 4217 code.
    """
    name = name.strip()
    if not name:
        raise ValueError("Account name must not be empty")
    if not _CURRENCY_CODE.fullmatch(currency):
        raise ValueError(f"Currency must be a three-letter code such as 'CAD', got {currency!r}")
    institution = (institution or "").strip() or None

    row = conn.execute(
        "INSERT INTO accounts (name, institution, type, currency) VALUES (?, ?, ?, ?) "
        "RETURNING id, name, institution, type, currency",
        (name, institution, account_type.value, currency),
    ).fetchone()
    return _to_account(row)


def get_account(conn: sqlite3.Connection, account_id: int) -> Account:
    """Raises: NotFoundError: if there is no such account."""
    row = conn.execute(
        "SELECT id, name, institution, type, currency FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Account {account_id} does not exist")
    return _to_account(row)


def list_accounts(conn: sqlite3.Connection) -> list[Account]:
    """Every account, in the order they were added."""
    rows = conn.execute(
        "SELECT id, name, institution, type, currency FROM accounts ORDER BY id"
    ).fetchall()
    return [_to_account(row) for row in rows]


def _to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        name=row["name"],
        institution=row["institution"],
        type=AccountType(row["type"]),
        currency=row["currency"],
    )
