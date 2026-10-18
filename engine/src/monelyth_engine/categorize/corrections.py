"""Learning from the user's corrections (PLAN.md 3.8).

When the user sets a category, the merchant is remembered with it (source ``user``), so every
later transaction from that merchant gets the same category. The user is then offered to give
it to the earlier ones too ("Apply to all 14 from Blue Bottle?"), which only changes
transactions the user hasn't categorized themselves.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from monelyth_engine.categorize.memory import memory_key
from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.categorization import automatic_merchants, set_remembered_category
from monelyth_engine.db.memory import remember
from monelyth_engine.db.models import CategorySource, Transaction
from monelyth_engine.db.transactions import get_transaction


class NothingToApplyError(ValueError):
    """The transaction has no category to give the others. The message is shown to the user."""


@dataclass(frozen=True, slots=True)
class SameMerchant:
    merchant: str | None
    """The transaction's merchant name, as shown."""
    transaction_ids: tuple[int, ...]
    """The other transactions from that merchant with a different category (or none), that
    automatic categorization may change: not set by the user, not linked as transfers."""


def remember_choice(conn: sqlite3.Connection, transaction: Transaction) -> None:
    """Save the category the user just gave ``transaction`` to merchant memory.

    Does nothing for a transaction without a user-set category or without a merchant name.
    """
    if transaction.category_id is None or transaction.category_source is not CategorySource.USER:
        return
    key = memory_key(transaction.merchant)
    if key is not None:
        remember(conn, key, category_id=transaction.category_id, source=CategorySource.USER)


def same_merchant(conn: sqlite3.Connection, transaction_id: int) -> SameMerchant:
    """Raises: NotFoundError: if there is no such transaction."""
    transaction = get_transaction(conn, transaction_id)
    return SameMerchant(
        merchant=transaction.merchant, transaction_ids=tuple(_others(conn, transaction))
    )


def apply_to_same_merchant(conn: sqlite3.Connection, transaction_id: int) -> int:
    """Give the transaction's category to the others from its merchant (see
    :class:`SameMerchant`), as merchant memory would. Returns how many changed.

    Raises:
        NotFoundError: if there is no such transaction.
        NothingToApplyError: if the transaction has no category yet.
    """
    with atomic(conn):
        transaction = get_transaction(conn, transaction_id)
        if transaction.category_id is None:
            raise NothingToApplyError(
                "This transaction has no category yet, so there's nothing to apply."
            )
        return set_remembered_category(conn, _others(conn, transaction), transaction.category_id)


def _others(conn: sqlite3.Connection, transaction: Transaction) -> list[int]:
    key = memory_key(transaction.merchant)
    if key is None or transaction.category_id is None:
        return []
    keys: dict[str, str | None] = {}
    others: list[int] = []
    for row in automatic_merchants(conn):
        if row.id == transaction.id or row.category_id == transaction.category_id:
            continue
        if row.merchant is None:
            continue
        # Most transactions repeat a few hundred merchant names; key each name once.
        if row.merchant not in keys:
            keys[row.merchant] = memory_key(row.merchant)
        if keys[row.merchant] == key:
            others.append(row.id)
    return others
