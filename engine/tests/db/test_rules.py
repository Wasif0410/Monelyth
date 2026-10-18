from __future__ import annotations

import sqlite3

import pytest

from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.rules import (
    ReadOnlyRuleError,
    Rule,
    RuleAuthor,
    RuleMatchType,
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    update_rule,
)

CONTAINS = RuleMatchType.CONTAINS


@pytest.fixture
def ids(db: sqlite3.Connection) -> dict[str, int]:
    return {category.name: category.id for category in list_categories(db)}


def _system_rule(db: sqlite3.Connection) -> Rule:
    return next(rule for rule in list_rules(db) if rule.created_by is RuleAuthor.SYSTEM)


def test_create_and_get(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    rule = create_rule(
        db, pattern="blue bottle", match_type=CONTAINS, category_id=ids["Coffee"], priority=5
    )

    assert rule == Rule(rule.id, "blue bottle", CONTAINS, ids["Coffee"], 5, RuleAuthor.USER)
    assert get_rule(db, rule.id) == rule


def test_list_puts_user_rules_first_then_priority_then_longest(
    db: sqlite3.Connection, ids: dict[str, int]
) -> None:
    low = create_rule(db, pattern="a", match_type=CONTAINS, category_id=ids["Other"], priority=0)
    long = create_rule(db, pattern="abc", match_type=CONTAINS, category_id=ids["Other"], priority=0)
    high = create_rule(db, pattern="b", match_type=CONTAINS, category_id=ids["Other"], priority=9)

    rules = list_rules(db)

    assert rules[:3] == [high, long, low]
    assert all(rule.created_by is RuleAuthor.SYSTEM for rule in rules[3:])
    system = [(-rule.priority, -len(rule.pattern)) for rule in rules[3:]]
    assert system == sorted(system)


def test_update_replaces_every_field(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    rule = create_rule(
        db, pattern="uber", match_type=CONTAINS, category_id=ids["Other"], priority=0
    )

    updated = update_rule(
        db,
        rule.id,
        pattern=r"^uber\b",
        match_type=RuleMatchType.REGEX,
        category_id=ids["Rideshare"],
        priority=3,
    )

    assert updated == Rule(
        rule.id, r"^uber\b", RuleMatchType.REGEX, ids["Rideshare"], 3, RuleAuthor.USER
    )


def test_delete_returns_the_rule(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    rule = create_rule(
        db, pattern="uber", match_type=CONTAINS, category_id=ids["Other"], priority=0
    )

    assert delete_rule(db, rule.id) == rule
    with pytest.raises(NotFoundError):
        get_rule(db, rule.id)


def test_default_rules_are_read_only(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    system = _system_rule(db)

    with pytest.raises(ReadOnlyRuleError, match="can't be changed"):
        update_rule(
            db, system.id, pattern="x", match_type=CONTAINS, category_id=ids["Other"], priority=0
        )
    with pytest.raises(ReadOnlyRuleError):
        delete_rule(db, system.id)
    assert get_rule(db, system.id) == system


def test_unknown_rule_or_category(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    with pytest.raises(NotFoundError, match="Category 999"):
        create_rule(db, pattern="x", match_type=CONTAINS, category_id=999, priority=0)
    with pytest.raises(NotFoundError, match="Rule 999"):
        update_rule(db, 999, pattern="x", match_type=CONTAINS, category_id=ids["Other"], priority=0)
    with pytest.raises(NotFoundError, match="Rule 999"):
        delete_rule(db, 999)
