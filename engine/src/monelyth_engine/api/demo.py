"""Demo data, for trying Monelyth before importing a real statement."""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from monelyth_engine.api.accounts import AccountOut
from monelyth_engine.api.deps import Connection
from monelyth_engine.api.imports import ImportResultOut
from monelyth_engine.demo import DemoData, DemoDataExistsError, add_demo_data

router = APIRouter(prefix="/demo", tags=["demo"])

_Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class DemoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: _Currency
    """ISO 4217 code for both demo accounts, e.g. ``CAD``."""


class DemoOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    accounts: list[AccountOut]
    """The demo checking account, then the demo card."""
    imports: list[ImportResultOut]
    """One import per account, in the same order."""
    transactions_added: int

    @classmethod
    def of(cls, data: DemoData) -> DemoOut:
        imports = [ImportResultOut.of(item.outcome) for item in data.imports]
        return cls(
            accounts=[AccountOut.of(item.account) for item in data.imports],
            imports=imports,
            transactions_added=sum(item.added for item in imports),
        )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "The demo data was added before"}},
)
def post_demo(body: DemoCreate, conn: Connection) -> DemoOut:
    """Add a demo checking account and credit card with a year of made-up transactions.

    The year ends today. The statements are imported exactly like an uploaded file.
    """
    try:
        data = add_demo_data(conn, currency=body.currency, today=_today())
    except DemoDataExistsError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from None
    return DemoOut.of(data)


def _today() -> datetime.date:
    """The computer's local date, so the demo ends on the user's today."""
    return datetime.date.today()
