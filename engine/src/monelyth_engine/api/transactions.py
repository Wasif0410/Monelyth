"""Listing and editing transactions."""

from __future__ import annotations

import datetime
from typing import Annotated, Final, Self

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from monelyth_engine.api.deps import Connection
from monelyth_engine.db.models import CategorySource, Transaction, TransactionFilter
from monelyth_engine.db.transactions import (
    list_transactions,
    transaction_date_range,
    update_transaction,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])

DEFAULT_PAGE_SIZE: Final = 100
MAX_PAGE_SIZE: Final = 500

_Merchant = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TransactionOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    account_id: int
    import_id: int | None
    posted_date: datetime.date
    amount_cents: int
    """Negative = money out, positive = money in."""
    description_raw: str
    merchant: str | None
    category_id: int | None
    category_source: CategorySource | None
    confidence: float | None
    needs_review: bool
    transfer_group: str | None

    @classmethod
    def of(cls, tx: Transaction) -> TransactionOut:
        return cls(
            id=tx.id,
            account_id=tx.account_id,
            import_id=tx.import_id,
            posted_date=tx.posted_date,
            amount_cents=tx.amount_cents,
            description_raw=tx.description_raw,
            merchant=tx.merchant,
            category_id=tx.category_id,
            category_source=tx.category_source,
            confidence=tx.confidence,
            needs_review=tx.needs_review,
            transfer_group=tx.transfer_group,
        )


class TransactionPageOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TransactionOut]
    total: int
    """How many transactions match across all pages."""


class TransactionRangeOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_date: datetime.date | None
    """The oldest ``posted_date``; ``None`` (like ``last_date``) when nothing is stored yet."""
    last_date: datetime.date | None


class TransactionUpdate(BaseModel):
    """The user's edits. Leave a field out to keep its current value."""

    model_config = ConfigDict(extra="forbid")

    category_id: Annotated[int, Field(ge=1)] | None = None
    merchant: _Merchant | None = None

    @model_validator(mode="after")
    def _require_a_change(self) -> Self:
        if self.category_id is None and self.merchant is None:
            raise ValueError("Give a category_id, a merchant, or both")
        return self


@router.get("")
def get_transactions(
    conn: Connection,
    account_id: Annotated[int | None, Query(ge=1)] = None,
    date_from: Annotated[datetime.date | None, Query(description="Inclusive")] = None,
    date_to: Annotated[datetime.date | None, Query(description="Inclusive")] = None,
    category_id: Annotated[int | None, Query(ge=1)] = None,
    categorized: Annotated[
        bool | None,
        Query(description="false: only uncategorized transactions; true: only categorized ones"),
    ] = None,
    needs_review: Annotated[
        bool | None, Query(description="true: only the review queue; false: everything else")
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="Search text")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionPageOut:
    page = list_transactions(
        conn,
        TransactionFilter(
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            categorized=categorized,
            needs_review=needs_review,
            search=q,
        ),
        limit=limit,
        offset=offset,
    )
    return TransactionPageOut(items=[TransactionOut.of(tx) for tx in page.items], total=page.total)


@router.get("/range")
def get_transaction_range(conn: Connection) -> TransactionRangeOut:
    """The dates of the oldest and newest stored transactions, e.g. to bound a month picker."""
    span = transaction_date_range(conn)
    if span is None:
        return TransactionRangeOut(first_date=None, last_date=None)
    return TransactionRangeOut(first_date=span[0], last_date=span[1])


@router.patch("/{transaction_id}")
def patch_transaction(
    transaction_id: int, body: TransactionUpdate, conn: Connection
) -> TransactionOut:
    tx = update_transaction(
        conn, transaction_id, category_id=body.category_id, merchant=body.merchant
    )
    return TransactionOut.of(tx)
