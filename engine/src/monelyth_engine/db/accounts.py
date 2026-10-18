"""Bank accounts and cards."""

from __future__ import annotations

import datetime
import re
import sqlite3
from dataclasses import dataclass
from typing import Final

from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.models import Account, AccountType

_CURRENCY_CODE: Final = re.compile(r"[A-Z]{3}")


@dataclass(frozen=True, slots=True)
class AccountStats:
    """What an account's stored transactions add up to."""

    transaction_count: int
    latest_transaction_date: datetime.date | None
    """The most recent transaction's date; ``None`` while the account has none."""
    net_amount_cents: int
    """The sum of every stored transaction's amount. This is not the bank balance: it leaves
    out whatever the account held before the earliest imported transaction."""


NO_TRANSACTIONS: Final = AccountStats(
    transaction_count=0, latest_transaction_date=None, net_amount_cents=0
)


@dataclass(frozen=True, slots=True)
class AccountDeletion:
    """What was removed together with a deleted account."""

    imports: int
    transactions: int


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
    name = _clean_name(name)
    if not _CURRENCY_CODE.fullmatch(currency):
        raise ValueError(f"Currency must be a three-letter code such as 'CAD', got {currency!r}")

    row = conn.execute(
        "INSERT INTO accounts (name, institution, type, currency) VALUES (?, ?, ?, ?) "
        "RETURNING id, name, institution, type, currency",
        (name, _clean_institution(institution), account_type.value, currency),
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


def update_account(
    conn: sqlite3.Connection, account_id: int, *, name: str, institution: str | None
) -> Account:
    """Set an account's name and institution, trimmed the way :func:`create_account` does.

    The type and currency can't change: every stored amount is in the account's currency.

    Raises:
        NotFoundError: if there is no such account.
        ValueError: if the name is blank.
    """
    row = conn.execute(
        "UPDATE accounts SET name = ?, institution = ? WHERE id = ? "
        "RETURNING id, name, institution, type, currency",
        (_clean_name(name), _clean_institution(institution), account_id),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Account {account_id} does not exist")
    return _to_account(row)


def delete_account(conn: sqlite3.Connection, account_id: int) -> AccountDeletion:
    """Delete an account with all of its imports and transactions, as one all-or-nothing step.

    Raises:
        NotFoundError: if there is no such account.
    """
    with atomic(conn):
        get_account(conn, account_id)
        # Children first: the foreign keys reject deleting a row that is still referenced.
        transactions = conn.execute(
            "DELETE FROM transactions WHERE account_id = ?", (account_id,)
        ).rowcount
        imports = conn.execute("DELETE FROM imports WHERE account_id = ?", (account_id,)).rowcount
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    return AccountDeletion(imports=imports, transactions=transactions)


def account_stats(
    conn: sqlite3.Connection, account_id: int | None = None
) -> dict[int, AccountStats]:
    """Stats by account ID, for every account or just ``account_id``.

    Accounts without transactions are left out; use :data:`NO_TRANSACTIONS` for them.
    """
    rows = conn.execute(
        "SELECT account_id, COUNT(*) AS count, MAX(posted_date) AS latest, "
        "SUM(amount_cents) AS net FROM transactions "
        "WHERE :account_id IS NULL OR account_id = :account_id GROUP BY account_id",
        {"account_id": account_id},
    ).fetchall()
    return {
        row["account_id"]: AccountStats(
            transaction_count=row["count"],
            latest_transaction_date=datetime.date.fromisoformat(row["latest"]),
            net_amount_cents=row["net"],
        )
        for row in rows
    }


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Account name must not be empty")
    return name


def _clean_institution(institution: str | None) -> str | None:
    return (institution or "").strip() or None


def _to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        name=row["name"],
        institution=row["institution"],
        type=AccountType(row["type"]),
        currency=row["currency"],
    )
