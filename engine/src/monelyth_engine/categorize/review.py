"""The review queue: transactions flagged ``needs_review`` (PLAN.md 3.7).

A transaction lands there when a tier answered with low confidence (it keeps the suggested
category) or when no tier answered (it has none). Accepting a suggestion is the user saying
"yes, that's right": the category becomes the user's own choice, leaves the queue, and is
remembered for the merchant, exactly as if the user had picked it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from typing import Final

from monelyth_engine.categorize.memory import memory_key
from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.categorization import AcceptedSuggestion, accept_suggestions
from monelyth_engine.db.memory import remember
from monelyth_engine.db.models import CategorySource, TransactionFilter
from monelyth_engine.db.transactions import list_transactions

_PAGE: Final = 500


def accept(conn: sqlite3.Connection, transaction_ids: Sequence[int]) -> int:
    """Accept the suggested category of each listed transaction that is waiting for review with
    one. Others (already reviewed, without a suggestion, or unknown) are skipped. Returns how
    many were accepted."""
    with atomic(conn):
        return _remember(conn, accept_suggestions(conn, list(dict.fromkeys(transaction_ids))))


def accept_matching(conn: sqlite3.Connection, filters: TransactionFilter) -> int:
    """Accept every suggestion in the review queue that matches ``filters`` (whose own
    ``needs_review`` and ``categorized`` are ignored). Returns how many were accepted."""
    queue = replace(filters, needs_review=True, categorized=True)
    with atomic(conn):
        # Inside one write transaction, so the pages can't shift while they are read.
        ids: list[int] = []
        while True:
            page = list_transactions(conn, queue, limit=_PAGE, offset=len(ids))
            ids.extend(tx.id for tx in page.items)
            if len(page.items) < _PAGE:
                break
        return _remember(conn, accept_suggestions(conn, ids))


def _remember(conn: sqlite3.Connection, accepted: Sequence[AcceptedSuggestion]) -> int:
    for item in accepted:
        key = memory_key(item.merchant)
        if key is not None:
            remember(conn, key, category_id=item.category_id, source=CategorySource.USER)
    return len(accepted)
