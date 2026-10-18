"""Merchant memory: "this merchant is always this category".

Entries are keyed by :func:`~monelyth_engine.normalize.merchant_key` of the cleaned merchant
name (stored in the ``merchant`` column), so "Blue Bottle" and "BLUE-BOTTLE" share one entry.

Who wrote an entry decides what may replace it: the user's own choice is never overwritten by
the classifier or the LLM, while the user can always overwrite theirs.
"""

from __future__ import annotations

import datetime
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from monelyth_engine.db.models import CategorySource

MEMORY_SOURCES: Final = frozenset(
    {CategorySource.USER, CategorySource.CLASSIFIER, CategorySource.LLM}
)
"""Who may write merchant memory. Rules are not remembered: they apply by themselves."""


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    key: str
    category_id: int
    source: CategorySource
    updated_at: datetime.datetime


def load_memory(conn: sqlite3.Connection) -> dict[str, MemoryEntry]:
    """Every entry, by merchant key."""
    rows = conn.execute(
        "SELECT merchant, category_id, source, updated_at FROM merchant_memory"
    ).fetchall()
    return {
        row["merchant"]: MemoryEntry(
            key=row["merchant"],
            category_id=row["category_id"],
            source=CategorySource(row["source"]),
            updated_at=datetime.datetime.fromisoformat(row["updated_at"]),
        )
        for row in rows
    }


def remember(
    conn: sqlite3.Connection,
    key: str,
    *,
    category_id: int,
    source: CategorySource,
    now: datetime.datetime | None = None,
) -> bool:
    """Save ``key`` → ``category_id``, unless that would overwrite the user's own entry with an
    automatic one. Returns whether the entry was written.

    Args:
        now: defaults to now; must be timezone-aware. Stored in UTC.

    Raises:
        ValueError: if ``key`` is empty, ``source`` may not write memory, or ``now`` is naive.
        sqlite3.IntegrityError: if the category does not exist.
    """
    if not key:
        raise ValueError("A merchant key must not be empty")
    if source not in MEMORY_SOURCES:
        raise ValueError(f"{source.value!r} does not write merchant memory")
    if now is None:
        now = datetime.datetime.now(datetime.UTC)
    elif now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    cursor = conn.execute(
        "INSERT INTO merchant_memory (merchant, category_id, source, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (merchant) DO UPDATE SET category_id = excluded.category_id, "
        "source = excluded.source, updated_at = excluded.updated_at "
        "WHERE merchant_memory.source != 'user' OR excluded.source = 'user'",
        (
            key,
            category_id,
            source.value,
            now.astimezone(datetime.UTC).isoformat(timespec="seconds"),
        ),
    )
    return cursor.rowcount == 1


def forget(conn: sqlite3.Connection, keys: Iterable[str]) -> int:
    """Delete the entries for ``keys``, whoever wrote them. Returns how many were deleted."""
    deleted = 0
    for key in set(keys):
        deleted += conn.execute("DELETE FROM merchant_memory WHERE merchant = ?", (key,)).rowcount
    return deleted
