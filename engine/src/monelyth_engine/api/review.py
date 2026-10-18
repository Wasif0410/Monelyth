"""The review queue: how much is waiting, and accepting suggested categories.

The queue's transactions themselves come from ``GET /transactions?needs_review=true``.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Final

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from monelyth_engine.api.deps import Connection
from monelyth_engine.categorize.review import accept, accept_matching
from monelyth_engine.db.categorization import review_counts
from monelyth_engine.db.models import TransactionFilter

router = APIRouter(prefix="/review", tags=["review"])

MAX_ACCEPT_IDS: Final = 1000


class ReviewSummaryOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    waiting: int
    """Transactions in the review queue."""
    with_suggestion: int
    """Of those, how many have a suggested category that can be accepted."""


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_ids: Annotated[
        list[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=MAX_ACCEPT_IDS)
    ]


class AcceptAllRequest(BaseModel):
    """Which part of the queue to accept, as for ``GET /transactions``. Every field left out
    matches everything, so ``{}`` accepts every suggestion waiting for review."""

    model_config = ConfigDict(extra="forbid")

    account_id: Annotated[int, Field(ge=1)] | None = None
    date_from: datetime.date | None = None
    """Inclusive."""
    date_to: datetime.date | None = None
    """Inclusive."""
    category_id: Annotated[int, Field(ge=1)] | None = None
    q: Annotated[str, Field(max_length=200)] | None = None
    """Search text."""


class AcceptedOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: int


@router.get("/summary")
def get_review_summary(conn: Connection) -> ReviewSummaryOut:
    counts = review_counts(conn)
    return ReviewSummaryOut(waiting=counts.waiting, with_suggestion=counts.with_suggestion)


@router.post("/accept")
def post_accept(body: AcceptRequest, conn: Connection) -> AcceptedOut:
    """Accept the suggested category of each listed transaction: it becomes your choice, leaves
    the queue and is remembered for its merchant. Transactions that aren't waiting for review
    with a suggestion are skipped and not counted."""
    return AcceptedOut(accepted=accept(conn, body.transaction_ids))


@router.post("/accept-all")
def post_accept_all(body: AcceptAllRequest, conn: Connection) -> AcceptedOut:
    """Accept every suggestion in the review queue that matches the filters."""
    filters = TransactionFilter(
        account_id=body.account_id,
        date_from=body.date_from,
        date_to=body.date_to,
        category_id=body.category_id,
        search=body.q,
    )
    return AcceptedOut(accepted=accept_matching(conn, filters))
