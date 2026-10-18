from __future__ import annotations

import datetime
import sqlite3

import pytest

from monelyth_engine.categorize.models import CategorizationInput
from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.models import Category
from monelyth_engine.db.rules import Rule, RuleAuthor, RuleMatchType
from tests.db.conftest import account, db, db_path, import_statement

# The database fixtures, shared with the storage tests.
__all__ = ["account", "db", "db_path", "import_statement"]


def item(
    description: str,
    merchant: str | None = None,
    *,
    transaction_id: int = 1,
    amount_cents: int = -1000,
) -> CategorizationInput:
    return CategorizationInput(
        transaction_id=transaction_id,
        account_id=1,
        posted_date=datetime.date(2026, 9, 1),
        amount_cents=amount_cents,
        description=description,
        merchant=merchant,
    )


def rule(
    pattern: str,
    category_id: int,
    *,
    rule_id: int = 1,
    match_type: RuleMatchType = RuleMatchType.CONTAINS,
    priority: int = 0,
    created_by: RuleAuthor = RuleAuthor.USER,
) -> Rule:
    return Rule(
        id=rule_id,
        pattern=pattern,
        match_type=match_type,
        category_id=category_id,
        priority=priority,
        created_by=created_by,
    )


@pytest.fixture
def categories(db: sqlite3.Connection) -> dict[str, Category]:
    """The default categories, by name."""
    return {category.name: category for category in list_categories(db)}
