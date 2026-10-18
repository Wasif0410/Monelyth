from __future__ import annotations

import sqlite3

import pytest

from monelyth_engine.categorize.rule_editing import (
    DuplicateRuleError,
    RuleDraft,
    RulePreview,
    add_rule,
    change_rule,
    preview_rule,
    remove_rule,
)
from monelyth_engine.categorize.rules import RulePatternError
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.memory import load_memory, remember
from monelyth_engine.db.models import Category, CategorySource, Transaction
from monelyth_engine.db.rules import ReadOnlyRuleError, RuleAuthor, RuleMatchType, list_rules
from monelyth_engine.db.transactions import get_transaction, update_transaction
from tests.db.conftest import ImportStatement, raw

CONTAINS = RuleMatchType.CONTAINS


@pytest.fixture
def txs(db: sqlite3.Connection, import_statement: ImportStatement) -> list[Transaction]:
    import_statement(
        [
            raw(1, -1650, "UBER* EATS PENDING"),
            raw(2, -2318, "UBER *TRIP"),
            raw(3, -2210, "UBER *TRIP"),
            raw(4, -999, "LYFT RIDE"),
        ],
        file_label="sept",
        merchants=["Uber Eats", "Uber", "Uber", "Lyft"],
    )
    rows = db.execute("SELECT id FROM transactions ORDER BY id").fetchall()
    return [get_transaction(db, row["id"]) for row in rows]


def _draft(
    pattern: str,
    category: Category,
    *,
    match_type: RuleMatchType = CONTAINS,
    priority: int = 0,
) -> RuleDraft:
    return RuleDraft(
        pattern=pattern, match_type=match_type, category_id=category.id, priority=priority
    )


def test_preview_counts_matches_and_the_users_own(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    update_transaction(db, txs[1].id, category_id=categories["Transport"].id)

    assert preview_rule(db, " uber ", CONTAINS) == RulePreview(
        matching=3, user_set=1, examples=("Uber", "Uber Eats")
    )
    assert preview_rule(db, r"^lyft\b", RuleMatchType.REGEX) == RulePreview(1, 0, ("Lyft",))
    with pytest.raises(RulePatternError):
        preview_rule(db, "(a+)+", RuleMatchType.REGEX)


def test_add_reports_the_automatic_transactions_it_matches(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    update_transaction(db, txs[1].id, category_id=categories["Transport"].id)

    change = add_rule(db, _draft("  uber   trip ", categories["Transport"]))

    assert change.rule.pattern == "uber trip"
    assert change.rule.created_by is RuleAuthor.USER
    assert change.affected_ids == {txs[2].id}


def test_change_reports_what_it_matched_before_and_after(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    rule = add_rule(db, _draft("lyft", categories["Rideshare"])).rule

    change = change_rule(db, rule.id, _draft("uber eats", categories["Dining Out"], priority=4))

    assert (change.rule.pattern, change.rule.priority) == ("uber eats", 4)
    assert change.affected_ids == {txs[0].id, txs[3].id}


def test_remove_reports_what_it_matched(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    rule = add_rule(db, _draft("lyft", categories["Rideshare"])).rule

    change = remove_rule(db, rule.id)

    assert change.affected_ids == {txs[3].id}
    assert rule.id not in {r.id for r in list_rules(db)}


def test_a_user_rule_pattern_must_be_new(
    db: sqlite3.Connection, categories: dict[str, Category]
) -> None:
    first = add_rule(db, _draft("Blue Bottle", categories["Coffee"])).rule
    other = add_rule(db, _draft("starbucks", categories["Coffee"])).rule

    # Matching ignores case and punctuation, so these are the same rule.
    with pytest.raises(DuplicateRuleError, match="You already have a rule for “Blue Bottle”"):
        add_rule(db, _draft("blue-bottle", categories["Dining Out"]))
    with pytest.raises(DuplicateRuleError):
        change_rule(db, other.id, _draft("BLUE BOTTLE", categories["Coffee"]))
    # The same pattern as a regex is a different rule, and a rule may keep its own pattern.
    add_rule(db, _draft("Blue Bottle", categories["Coffee"], match_type=RuleMatchType.REGEX))
    change_rule(db, first.id, _draft("blue bottle", categories["Dining Out"]))


def test_a_default_rule_may_share_a_pattern(
    db: sqlite3.Connection, categories: dict[str, Category]
) -> None:
    # Defaults include "uber"; a user rule overrides it rather than duplicating it.
    assert add_rule(db, _draft("uber", categories["Transport"])).rule.pattern == "uber"


def test_default_rules_and_bad_input_are_refused(
    db: sqlite3.Connection, categories: dict[str, Category]
) -> None:
    system = next(rule for rule in list_rules(db) if rule.created_by is RuleAuthor.SYSTEM)

    with pytest.raises(ReadOnlyRuleError):
        change_rule(db, system.id, _draft("x", categories["Other"]))
    with pytest.raises(ReadOnlyRuleError):
        remove_rule(db, system.id)
    with pytest.raises(RulePatternError):
        add_rule(db, _draft("[", categories["Other"], match_type=RuleMatchType.REGEX))
    with pytest.raises(NotFoundError):
        change_rule(db, 99_999, _draft("x", categories["Other"]))


def test_a_new_rule_takes_over_from_merchant_memory(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    remember(db, "uber", category_id=categories["Transport"].id, source=CategorySource.USER)
    remember(db, "lyft", category_id=categories["Transport"].id, source=CategorySource.USER)
    remember(db, "uber eats", category_id=categories["Groceries"].id, source=CategorySource.LLM)

    add_rule(db, _draft("uber", categories["Rideshare"]))

    # "uber" is a whole word of both "Uber" and "Uber Eats", so both are forgotten.
    assert set(load_memory(db)) == {"lyft"}


def test_deleting_a_rule_forgets_nothing(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    rule = add_rule(db, _draft("lyft", categories["Rideshare"])).rule
    remember(db, "lyft", category_id=categories["Transport"].id, source=CategorySource.USER)

    remove_rule(db, rule.id)

    assert set(load_memory(db)) == {"lyft"}
