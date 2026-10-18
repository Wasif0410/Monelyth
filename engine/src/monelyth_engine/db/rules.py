"""Keyword and regex rules: the defaults Monelyth ships with and the ones the user adds.

These functions store rules as given; checking that a pattern is valid and safe to run is
:mod:`monelyth_engine.categorize.rules`' job, before anything reaches the database.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.categories import require_category
from monelyth_engine.db.errors import NotFoundError

_SELECT: Final = "SELECT id, pattern, match_type, category_id, priority, created_by FROM rules"
_MATCH_ORDER: Final = "ORDER BY created_by = 'user' DESC, priority DESC, length(pattern) DESC, id"


class RuleMatchType(StrEnum):
    CONTAINS = "contains"
    """Whole words of the merchant name or the description, ignoring case and punctuation."""
    REGEX = "regex"
    """A regular expression searched case-insensitively in the same texts."""


class RuleAuthor(StrEnum):
    SYSTEM = "system"
    """Shipped with Monelyth; read-only."""
    USER = "user"


@dataclass(frozen=True, slots=True)
class Rule:
    id: int
    pattern: str
    match_type: RuleMatchType
    category_id: int
    priority: int
    """Among rules by the same author, the highest priority that matches wins."""
    created_by: RuleAuthor


class ReadOnlyRuleError(ValueError):
    """A default rule was to be changed or deleted. The message is shown to the user."""

    def __init__(self) -> None:
        super().__init__(
            "Monelyth's default rules can't be changed. Add your own rule instead: "
            "yours always come before the defaults."
        )


def list_rules(conn: sqlite3.Connection) -> list[Rule]:
    """Every rule in the order they are tried: the user's first, then the defaults, each by
    priority (highest first), then longest pattern first, so the most specific match wins."""
    return [_to_rule(row) for row in conn.execute(f"{_SELECT} {_MATCH_ORDER}").fetchall()]


def get_rule(conn: sqlite3.Connection, rule_id: int) -> Rule:
    """Raises: NotFoundError: if there is no such rule."""
    row = conn.execute(f"{_SELECT} WHERE id = ?", (rule_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Rule {rule_id} does not exist")
    return _to_rule(row)


def create_rule(
    conn: sqlite3.Connection,
    *,
    pattern: str,
    match_type: RuleMatchType,
    category_id: int,
    priority: int,
) -> Rule:
    """Add a rule made by the user.

    Raises:
        NotFoundError: if the category does not exist.
    """
    with atomic(conn):
        require_category(conn, category_id)
        row = conn.execute(
            "INSERT INTO rules (pattern, match_type, category_id, priority, created_by) "
            "VALUES (?, ?, ?, ?, ?) "
            "RETURNING id, pattern, match_type, category_id, priority, created_by",
            (pattern, match_type.value, category_id, priority, RuleAuthor.USER.value),
        ).fetchone()
        return _to_rule(row)


def update_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    *,
    pattern: str,
    match_type: RuleMatchType,
    category_id: int,
    priority: int,
) -> Rule:
    """Replace every field of one of the user's rules and return the result.

    Raises:
        NotFoundError: if the rule or the category does not exist.
        ReadOnlyRuleError: if the rule is one of the defaults.
    """
    with atomic(conn):
        _require_user_rule(conn, rule_id)
        require_category(conn, category_id)
        conn.execute(
            "UPDATE rules SET pattern = ?, match_type = ?, category_id = ?, priority = ? "
            "WHERE id = ?",
            (pattern, match_type.value, category_id, priority, rule_id),
        )
        return get_rule(conn, rule_id)


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> Rule:
    """Delete one of the user's rules and return it as it was.

    Raises:
        NotFoundError: if there is no such rule.
        ReadOnlyRuleError: if the rule is one of the defaults.
    """
    with atomic(conn):
        rule = _require_user_rule(conn, rule_id)
        conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        return rule


def _require_user_rule(conn: sqlite3.Connection, rule_id: int) -> Rule:
    rule = get_rule(conn, rule_id)
    if rule.created_by is not RuleAuthor.USER:
        raise ReadOnlyRuleError
    return rule


def _to_rule(row: sqlite3.Row) -> Rule:
    return Rule(
        id=row["id"],
        pattern=row["pattern"],
        match_type=RuleMatchType(row["match_type"]),
        category_id=row["category_id"],
        priority=row["priority"],
        created_by=RuleAuthor(row["created_by"]),
    )
