"""Bank accounts and cards."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from monelyth_engine.api.deps import Connection
from monelyth_engine.db.accounts import create_account, list_accounts
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

    @classmethod
    def of(cls, account: Account) -> AccountOut:
        return cls(
            id=account.id,
            name=account.name,
            institution=account.institution,
            type=account.type,
            currency=account.currency,
        )


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: _Name
    type: AccountType
    currency: _Currency
    """ISO 4217 code, e.g. ``CAD``."""
    institution: _Institution | None = None


@router.get("")
def get_accounts(conn: Connection) -> list[AccountOut]:
    return [AccountOut.of(account) for account in list_accounts(conn)]


@router.post("", status_code=status.HTTP_201_CREATED)
def post_account(body: AccountCreate, conn: Connection) -> AccountOut:
    account = create_account(
        conn,
        name=body.name,
        account_type=body.type,
        currency=body.currency,
        institution=body.institution,
    )
    return AccountOut.of(account)
