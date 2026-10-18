"""Adding, changing and deleting the user's rules, and previewing what a pattern matches.

Each change reports the transactions it may re-categorize (PLAN.md 3.10): those the rule
matched before or matches now, among the ones automatic categorization may change. The caller
queues a run over them; categories the user set are never among them.

A new or changed rule also takes over from merchant memory for the merchants it matches: what
was learned about them, even from the user's own corrections, is forgotten, so the rule the
user just wrote is what applies to them from now on. Without that, an earlier correction
(which merchant memory ranks above rules) would silently keep the new rule from doing anything.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final

from monelyth_engine.categorize.memory import memory_key
from monelyth_engine.categorize.rules import (
    MatchTexts,
    PatternMatcher,
    clean_pattern,
    prepare_rules,
)
from monelyth_engine.db.atomic import atomic, read_snapshot
from monelyth_engine.db.categorization import transaction_texts
from monelyth_engine.db.memory import forget
from monelyth_engine.db.rules import (
    Rule,
    RuleAuthor,
    RuleMatchType,
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    update_rule,
)
from monelyth_engine.normalize import merchant_key

PREVIEW_EXAMPLES: Final = 5


class DuplicateRuleError(ValueError):
    """The user already has a rule with this pattern. The message is shown to the user."""

    def __init__(self, existing: Rule) -> None:
        super().__init__(
            f"You already have a rule for “{existing.pattern}”. Edit that one instead."
        )
        self.existing = existing


@dataclass(frozen=True, slots=True)
class RuleDraft:
    """A rule as the user entered it, before its pattern is checked."""

    pattern: str
    match_type: RuleMatchType
    category_id: int
    priority: int


@dataclass(frozen=True, slots=True)
class RuleChange:
    rule: Rule
    """The rule as saved, or as it was before being deleted."""
    affected_ids: frozenset[int]
    """Transactions to re-categorize."""


@dataclass(frozen=True, slots=True)
class RulePreview:
    matching: int
    """Stored transactions the pattern matches."""
    user_set: int
    """Of those, how many the user categorized (or are linked transfers): a rule never changes
    them."""
    examples: tuple[str, ...]
    """Up to :data:`PREVIEW_EXAMPLES` distinct merchant names it matches, most frequent first."""


def preview_rule(conn: sqlite3.Connection, pattern: str, match_type: RuleMatchType) -> RulePreview:
    """What a rule with this pattern would match, without saving anything.

    Raises:
        RulePatternError: if the pattern can't be used.
    """
    matcher = PatternMatcher.compile(pattern, match_type)
    matching = 0
    user_set = 0
    names: dict[str, int] = {}
    with read_snapshot(conn):
        for text in transaction_texts(conn):
            if not matcher.matches(MatchTexts.of(text.merchant, text.description_raw)):
                continue
            matching += 1
            user_set += not text.automatic
            name = text.merchant or text.description_raw
            names[name] = names.get(name, 0) + 1
    examples = sorted(names, key=lambda name: (-names[name], name))[:PREVIEW_EXAMPLES]
    return RulePreview(matching=matching, user_set=user_set, examples=tuple(examples))


def add_rule(conn: sqlite3.Connection, draft: RuleDraft) -> RuleChange:
    """Raises:
    RulePatternError: if the pattern can't be used.
    DuplicateRuleError: if the user already has a rule with this pattern and match type.
    NotFoundError: if the category does not exist.
    """
    pattern = clean_pattern(draft.pattern, draft.match_type)
    with atomic(conn):
        _refuse_duplicate(conn, pattern, draft.match_type, exclude_id=None)
        rule = create_rule(
            conn,
            pattern=pattern,
            match_type=draft.match_type,
            category_id=draft.category_id,
            priority=draft.priority,
        )
        return RuleChange(rule, _take_over(conn, before=None, after=rule))


def change_rule(conn: sqlite3.Connection, rule_id: int, draft: RuleDraft) -> RuleChange:
    """Raises:
    RulePatternError: if the pattern can't be used.
    DuplicateRuleError: if another of the user's rules has this pattern and match type.
    NotFoundError: if the rule or the category does not exist.
    ReadOnlyRuleError: if the rule is one of the defaults.
    """
    pattern = clean_pattern(draft.pattern, draft.match_type)
    with atomic(conn):
        before = get_rule(conn, rule_id)
        _refuse_duplicate(conn, pattern, draft.match_type, exclude_id=rule_id)
        rule = update_rule(
            conn,
            rule_id,
            pattern=pattern,
            match_type=draft.match_type,
            category_id=draft.category_id,
            priority=draft.priority,
        )
        return RuleChange(rule, _take_over(conn, before=before, after=rule))


def remove_rule(conn: sqlite3.Connection, rule_id: int) -> RuleChange:
    """Raises:
    NotFoundError: if there is no such rule.
    ReadOnlyRuleError: if the rule is one of the defaults.
    """
    with atomic(conn):
        rule = delete_rule(conn, rule_id)
        return RuleChange(rule, _take_over(conn, before=rule, after=None))


def _refuse_duplicate(
    conn: sqlite3.Connection, pattern: str, match_type: RuleMatchType, *, exclude_id: int | None
) -> None:
    for rule in list_rules(conn):
        if (
            rule.created_by is RuleAuthor.USER
            and rule.id != exclude_id
            and rule.match_type is match_type
            and _same_pattern(rule.pattern, pattern, match_type)
        ):
            raise DuplicateRuleError(rule)


def _same_pattern(a: str, b: str, match_type: RuleMatchType) -> bool:
    if match_type is RuleMatchType.CONTAINS:
        # Matching ignores case and punctuation, so neither may tell two rules apart.
        return merchant_key(a) == merchant_key(b)
    return a == b


def _take_over(
    conn: sqlite3.Connection, *, before: Rule | None, after: Rule | None
) -> frozenset[int]:
    """After a rule changed from ``before`` to ``after`` (``None``: didn't exist / deleted),
    forget merchant memory for the merchants ``after`` matches and return the transactions to
    re-categorize."""
    old = _matcher(before)
    new = _matcher(after)
    affected: set[int] = set()
    taken_over: set[str] = set()
    for text in transaction_texts(conn):
        texts = MatchTexts.of(text.merchant, text.description_raw)
        matches_new = new is not None and new.matches(texts)
        if matches_new and (key := memory_key(text.merchant)) is not None:
            taken_over.add(key)
        if text.automatic and (matches_new or (old is not None and old.matches(texts))):
            affected.add(text.id)
    forget(conn, taken_over)
    return frozenset(affected)


def _matcher(rule: Rule | None) -> PatternMatcher | None:
    if rule is None:
        return None
    prepared = prepare_rules([rule])
    return prepared[0][1] if prepared else None
