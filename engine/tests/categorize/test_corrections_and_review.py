from __future__ import annotations

import sqlite3

import pytest

from monelyth_engine.categorize.corrections import (
    NothingToApplyError,
    apply_to_same_merchant,
    remember_choice,
    same_merchant,
)
from monelyth_engine.categorize.review import accept, accept_matching
from monelyth_engine.db.categorization import review_counts
from monelyth_engine.db.memory import load_memory
from monelyth_engine.db.models import Category, CategorySource, Transaction, TransactionFilter
from monelyth_engine.db.transactions import get_transaction, update_transaction
from tests.db.conftest import ImportStatement, raw


@pytest.fixture
def txs(db: sqlite3.Connection, import_statement: ImportStatement) -> list[Transaction]:
    import_statement(
        [
            raw(1, -525, "SQ *BLUE BOTTLE 0423"),
            raw(2, -610, "BLUE-BOTTLE COFFEE"),
            raw(3, -480, "SQ *BLUE BOTTLE 0423"),
            raw(4, -480, "BLUE BOTTLE ONLINE"),
            raw(5, -1299, "AMZN MKTP"),
        ],
        file_label="sept",
        merchants=["Blue Bottle", "BLUE-BOTTLE", "Blue Bottle", "Blue Bottle Online", "Amazon"],
    )
    rows = db.execute("SELECT id FROM transactions ORDER BY id").fetchall()
    return [get_transaction(db, row["id"]) for row in rows]


def _suggest(db: sqlite3.Connection, tx: Transaction, category_id: int, confidence: float) -> None:
    db.execute(
        "UPDATE transactions SET category_id = ?, category_source = 'classifier', "
        "confidence = ?, needs_review = ? WHERE id = ?",
        (category_id, confidence, int(confidence < 0.8), tx.id),
    )


def test_a_correction_is_remembered_for_the_merchant(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    corrected = update_transaction(db, txs[0].id, category_id=categories["Coffee"].id)

    remember_choice(db, corrected)

    entry = load_memory(db)["blue bottle"]
    assert (entry.category_id, entry.source) == (categories["Coffee"].id, CategorySource.USER)


def test_only_a_users_category_is_remembered(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    _suggest(db, txs[0], categories["Coffee"].id, 0.9)

    remember_choice(db, get_transaction(db, txs[0].id))
    remember_choice(db, txs[1])

    assert load_memory(db) == {}


def test_same_merchant_counts_the_others_that_would_change(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    coffee = categories["Coffee"].id
    # Already Coffee, so it would not change.
    _suggest(db, txs[2], coffee, 0.9)
    corrected = update_transaction(db, txs[0].id, category_id=coffee)

    found = same_merchant(db, corrected.id)

    # "BLUE-BOTTLE" shares the key; "Blue Bottle Online" and Amazon don't.
    assert found.merchant == "Blue Bottle"
    assert found.transaction_ids == (txs[1].id,)


def test_same_merchant_leaves_out_what_the_user_set(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    update_transaction(db, txs[1].id, category_id=categories["Dining Out"].id)
    corrected = update_transaction(db, txs[0].id, category_id=categories["Coffee"].id)

    assert same_merchant(db, corrected.id).transaction_ids == (txs[2].id,)


def test_apply_gives_the_others_the_category_as_memory_would(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    coffee = categories["Coffee"].id
    _suggest(db, txs[1], categories["Groceries"].id, 0.5)
    corrected = update_transaction(db, txs[0].id, category_id=coffee)

    assert apply_to_same_merchant(db, corrected.id) == 2

    for tx in (txs[1], txs[2]):
        after = get_transaction(db, tx.id)
        assert (after.category_id, after.category_source, after.confidence) == (
            coffee,
            CategorySource.MEMORY,
            1.0,
        )
        assert not after.needs_review
    assert get_transaction(db, txs[3].id).category_id is None
    assert same_merchant(db, corrected.id).transaction_ids == ()


def test_apply_needs_a_category(db: sqlite3.Connection, txs: list[Transaction]) -> None:
    with pytest.raises(NothingToApplyError, match="no category yet"):
        apply_to_same_merchant(db, txs[0].id)
    assert same_merchant(db, txs[0].id).transaction_ids == ()


def test_accepting_makes_the_suggestion_the_users_choice(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    coffee = categories["Coffee"].id
    _suggest(db, txs[0], coffee, 0.6)
    _suggest(db, txs[4], categories["Shopping"].id, 0.95)  # Not waiting for review.
    db.execute("UPDATE transactions SET needs_review = 1 WHERE id = ?", (txs[3].id,))

    accepted = accept(db, [txs[0].id, txs[0].id, txs[3].id, txs[4].id, 9999])

    assert accepted == 1
    after = get_transaction(db, txs[0].id)
    assert (after.category_id, after.category_source, after.confidence, after.needs_review) == (
        coffee,
        CategorySource.USER,
        None,
        False,
    )
    assert load_memory(db)["blue bottle"].source is CategorySource.USER
    # No suggestion to accept: it stays in the queue.
    assert get_transaction(db, txs[3].id).needs_review
    assert review_counts(db).waiting == 1


def test_accept_matching_takes_the_filters_but_only_suggestions(
    db: sqlite3.Connection, txs: list[Transaction], categories: dict[str, Category]
) -> None:
    coffee = categories["Coffee"].id
    for tx in txs[:3]:
        _suggest(db, tx, coffee, 0.6)
    _suggest(db, txs[4], categories["Shopping"].id, 0.6)
    db.execute("UPDATE transactions SET needs_review = 1 WHERE id = ?", (txs[3].id,))
    assert (review_counts(db).waiting, review_counts(db).with_suggestion) == (5, 4)

    assert accept_matching(db, TransactionFilter(search="blue", needs_review=False)) == 3

    assert (review_counts(db).waiting, review_counts(db).with_suggestion) == (2, 1)
    assert accept_matching(db, TransactionFilter()) == 1
    assert review_counts(db).waiting == 1
