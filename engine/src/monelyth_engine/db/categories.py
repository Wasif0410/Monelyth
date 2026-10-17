"""Spending and income categories."""

from __future__ import annotations

import sqlite3

from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.models import Category, CategoryKind


def list_categories(conn: sqlite3.Connection) -> list[Category]:
    """Every category, defaults first in their curated order, then any the user added."""
    rows = conn.execute("SELECT id, name, kind, parent_id FROM categories ORDER BY id").fetchall()
    return [
        Category(
            id=row["id"],
            name=row["name"],
            kind=CategoryKind(row["kind"]),
            parent_id=row["parent_id"],
        )
        for row in rows
    ]


def require_category(conn: sqlite3.Connection, category_id: int) -> None:
    """Raises: NotFoundError: if there is no such category."""
    if conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone() is None:
        raise NotFoundError(f"Category {category_id} does not exist")
