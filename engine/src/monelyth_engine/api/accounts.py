"""Bank accounts and cards."""

from __future__ import annotations

import datetime
import sqlite3
from typing import Annotated, Self

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from monelyth_engine.api.deps import Connection
from monelyth_engine.db.accounts import (
    NO_TRANSACTIONS,
    AccountStats,
    account_stats,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
)
from monelyth_engine.db.atomic import atomic, read_snapshot
from monelyth_engine.db.models import Account, AccountType

router = APIRouter(prefix="/accounts", tags=["accounts"])

_Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
_Institution = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
_Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class AccountOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    institution: str | None
    type: AccountType
    currency: str
    transaction_count: int
    latest_transaction_date: datetime.date | None
    """``None`` while the account has no transactions."""
    net_amount_cents: int
    """The sum of the account's imported transactions. Not the bank balance: whatever the
    account held before the earliest imported transaction is unknown."""

    @classmethod
    def of(cls, account: Account, stats: AccountStats) -> AccountOut:
        return cls(
            id=account.id,
            name=account.name,
            institution=account.institution,
            type=account.type,
            currency=account.currency,
            transaction_count=stats.transaction_count,
            latest_transaction_date=stats.latest_transaction_date,
            net_amount_cents=stats.net_amount_cents,
        )


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: _Name
    type: AccountType
    currency: _Currency
    """ISO 4217 code, e.g. ``CAD``."""
    institution: _Institution | None = None


class AccountUpdate(BaseModel):
    """The user's edits. Leave a field out to keep it; a blank or null institution clears it."""

    model_config = ConfigDict(extra="forbid")

    name: _Name | None = None
    """Can be left out, but not cleared."""
    institution: _Institution | None = None

    @model_validator(mode="after")
    def _name_is_not_cleared(self) -> Self:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("An account needs a name")
        return self


class AccountDeletionOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    deleted_imports: int
    deleted_transactions: int


@router.get("")
def get_accounts(conn: Connection) -> list[AccountOut]:
    with read_snapshot(conn):
        accounts = list_accounts(conn)
        stats = account_stats(conn)
    return [AccountOut.of(account, stats.get(account.id, NO_TRANSACTIONS)) for account in accounts]


@router.post("", status_code=status.HTTP_201_CREATED)
def post_account(body: AccountCreate, conn: Connection) -> AccountOut:
    account = create_account(
        conn,
        name=body.name,
        account_type=body.type,
        currency=body.currency,
        institution=body.institution,
    )
    # A new account has nothing imported yet.
    return AccountOut.of(account, NO_TRANSACTIONS)


@router.patch("/{account_id}")
def patch_account(account_id: int, body: AccountUpdate, conn: Connection) -> AccountOut:
    with atomic(conn):
        current = get_account(conn, account_id)
        account = update_account(
            conn,
            account_id,
            name=current.name if body.name is None else body.name,
            institution=(
                body.institution if "institution" in body.model_fields_set else current.institution
            ),
        )
        result = account_out(conn, account)
    return result


def account_out(conn: sqlite3.Connection, account: Account) -> AccountOut:
    """The response for one account, with stats read from the database now."""
    stats = account_stats(conn, account.id).get(account.id, NO_TRANSACTIONS)
    return AccountOut.of(account, stats)


@router.delete("/{account_id}")
def remove_account(account_id: int, conn: Connection) -> AccountDeletionOut:
    """Delete the account with all of its imports and transactions. This can't be undone."""
    deletion = delete_account(conn, account_id)
    return AccountDeletionOut(
        deleted_imports=deletion.imports, deleted_transactions=deletion.transactions
    )
