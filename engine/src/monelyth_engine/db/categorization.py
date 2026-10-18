"""The queries automatic categorization runs on the transactions table.

Every write here is guarded in SQL, not only by the caller: a transaction whose category the
user chose (``category_source = 'user'``) is never changed, and neither is one linked as a
transfer between the user's accounts (``transfer_group`` set), which the transfer pass owns.
The guard holds even when the user edits a transaction while a background run is working.
"""

from __future__ import annotations

import datetime
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from monelyth_engine.db.models import CategorySource

AUTOMATIC: Final = (
    "(category_source IS NULL OR category_source != 'user') AND transfer_group IS NULL"
)
"""SQL condition for the transactions automatic categorization may change."""

_IN_CHUNK: Final = 500
"""IDs per ``IN (...)`` list; far below SQLite's limit on bound parameters."""


@dataclass(frozen=True, slots=True)
class CategorizationState:
    """Where an automatically categorizable transaction stands."""

    id: int
    category_id: int | None
    needs_review: bool

    @property
    def unprocessed(self) -> bool:
        """Never looked at by the pipeline: stored without a category and not flagged.

        Once a run has seen a transaction it either has a category or is flagged for review
        because no tier could answer it."""
        return self.category_id is None and not self.needs_review


@dataclass(frozen=True, slots=True)
class CategorizationRow:
    """What the tiers may look at, for one transaction they may categorize."""

    id: int
    account_id: int
    posted_date: datetime.date
    amount_cents: int
    description_raw: str
    merchant: str | None


@dataclass(frozen=True, slots=True)
class CategoryAssignment:
    """The pipeline's verdict for one transaction."""

    transaction_id: int
    category_id: int | None
    """``None`` when no tier could answer; the transaction then waits in the review queue."""
    source: CategorySource | None
    confidence: float | None
    needs_review: bool

    def __post_init__(self) -> None:
        if self.source is CategorySource.USER:
            raise ValueError("automatic categorization never assigns as the user")
        if (self.category_id is None) != (self.source is None):
            raise ValueError("a category and its source come together")


@dataclass(frozen=True, slots=True)
class TransactionText:
    """The texts a rule is matched against, for one stored transaction."""

    id: int
    merchant: str | None
    description_raw: str
    automatic: bool
    """Whether automatic categorization may change it (see the module docstring)."""


@dataclass(frozen=True, slots=True)
class MerchantRow:
    id: int
    merchant: str | None
    category_id: int | None


def categorization_states(conn: sqlite3.Connection) -> list[CategorizationState]:
    """Every transaction automatic categorization may change, oldest stored first."""
    rows = conn.execute(
        f"SELECT id, category_id, needs_review FROM transactions WHERE {AUTOMATIC} ORDER BY id"  # noqa: S608
    ).fetchall()
    return [
        CategorizationState(
            id=row["id"], category_id=row["category_id"], needs_review=bool(row["needs_review"])
        )
        for row in rows
    ]


def categorization_rows(
    conn: sqlite3.Connection, transaction_ids: Sequence[int]
) -> list[CategorizationRow]:
    """The given transactions, in the given order, leaving out any that have meanwhile been
    deleted, set by the user or linked as a transfer."""
    found: dict[int, CategorizationRow] = {}
    for chunk in _chunks(transaction_ids):
        placeholders = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            "SELECT id, account_id, posted_date, amount_cents, description_raw, merchant "  # noqa: S608
            f"FROM transactions WHERE id IN ({placeholders}) AND {AUTOMATIC}",
            chunk,
        ).fetchall()
        for row in rows:
            found[row["id"]] = CategorizationRow(
                id=row["id"],
                account_id=row["account_id"],
                posted_date=datetime.date.fromisoformat(row["posted_date"]),
                amount_cents=row["amount_cents"],
                description_raw=row["description_raw"],
                merchant=row["merchant"],
            )
    return [found[tid] for tid in transaction_ids if tid in found]


def assign_categories(
    conn: sqlite3.Connection, assignments: Sequence[CategoryAssignment]
) -> set[int]:
    """Store each assignment, skipping transactions it may no longer change (see the module
    docstring). Returns the IDs that were updated.

    Call inside :func:`~monelyth_engine.db.atomic.atomic` to store a batch together.
    """
    updated: set[int] = set()
    for item in assignments:
        cursor = conn.execute(
            "UPDATE transactions SET category_id = ?, category_source = ?, confidence = ?, "  # noqa: S608
            f"needs_review = ? WHERE id = ? AND {AUTOMATIC}",
            (
                item.category_id,
                None if item.source is None else item.source.value,
                item.confidence,
                int(item.needs_review),
                item.transaction_id,
            ),
        )
        if cursor.rowcount == 1:
            updated.add(item.transaction_id)
    return updated


def transaction_texts(conn: sqlite3.Connection) -> Iterator[TransactionText]:
    """The merchant and description of every stored transaction, for matching rules."""
    cursor = conn.execute(
        f"SELECT id, merchant, description_raw, {AUTOMATIC} AS automatic "  # noqa: S608
        "FROM transactions ORDER BY id"
    )
    for row in cursor:
        yield TransactionText(
            id=row["id"],
            merchant=row["merchant"],
            description_raw=row["description_raw"],
            automatic=bool(row["automatic"]),
        )


def automatic_merchants(conn: sqlite3.Connection) -> list[MerchantRow]:
    """Merchant and category of every transaction automatic categorization may change."""
    rows = conn.execute(
        f"SELECT id, merchant, category_id FROM transactions WHERE {AUTOMATIC} ORDER BY id"  # noqa: S608
    ).fetchall()
    return [
        MerchantRow(id=row["id"], merchant=row["merchant"], category_id=row["category_id"])
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class AcceptedSuggestion:
    id: int
    merchant: str | None
    category_id: int


def accept_suggestions(
    conn: sqlite3.Connection, transaction_ids: Sequence[int]
) -> list[AcceptedSuggestion]:
    """Confirm the suggested category of each listed transaction that is waiting for review
    with one: it becomes the user's choice and leaves the queue. Others are skipped.

    Returns the transactions that were accepted. Call inside
    :func:`~monelyth_engine.db.atomic.atomic` together with the memory updates.
    """
    accepted: list[AcceptedSuggestion] = []
    for chunk in _chunks(transaction_ids):
        placeholders = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            "UPDATE transactions SET category_source = 'user', confidence = NULL, "  # noqa: S608
            f"needs_review = 0 WHERE id IN ({placeholders}) AND needs_review = 1 "
            "AND category_id IS NOT NULL RETURNING id, merchant, category_id",
            chunk,
        ).fetchall()
        accepted.extend(
            AcceptedSuggestion(
                id=row["id"], merchant=row["merchant"], category_id=row["category_id"]
            )
            for row in rows
        )
    return accepted


@dataclass(frozen=True, slots=True)
class ReviewCounts:
    waiting: int
    """Transactions in the review queue."""
    with_suggestion: int
    """Of those, how many have a suggested category that can be accepted as is."""


def review_counts(conn: sqlite3.Connection) -> ReviewCounts:
    row = conn.execute(
        "SELECT COUNT(*), COUNT(category_id) FROM transactions WHERE needs_review = 1"
    ).fetchone()
    return ReviewCounts(waiting=row[0], with_suggestion=row[1])


def set_remembered_category(
    conn: sqlite3.Connection, transaction_ids: Sequence[int], category_id: int
) -> int:
    """Give the listed transactions ``category_id`` as merchant memory's answer, as the pipeline
    would. Returns how many were changed. Call inside
    :func:`~monelyth_engine.db.atomic.atomic`."""
    changed = 0
    for chunk in _chunks(transaction_ids):
        placeholders = ", ".join("?" for _ in chunk)
        cursor = conn.execute(
            "UPDATE transactions SET category_id = ?, category_source = ?, confidence = 1.0, "  # noqa: S608
            f"needs_review = 0 WHERE id IN ({placeholders}) AND {AUTOMATIC}",
            [category_id, CategorySource.MEMORY.value, *chunk],
        )
        changed += cursor.rowcount
    return changed


def _chunks(ids: Sequence[int]) -> Iterator[list[int]]:
    for start in range(0, len(ids), _IN_CHUNK):
        yield list(ids[start : start + _IN_CHUNK])
