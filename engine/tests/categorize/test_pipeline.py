from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from monelyth_engine.categorize.models import CategorizationInput, Suggestion
from monelyth_engine.categorize.pipeline import (
    AUTOMATIC,
    BATCH_SIZE,
    UNCATEGORIZED,
    UNPROCESSED,
    ProgressCallback,
    RunResult,
    RunScope,
    TierRunner,
    run_categorization,
)
from monelyth_engine.categorize.tiers import PipelineExtensions
from monelyth_engine.db.connection import connect
from monelyth_engine.db.memory import load_memory, remember
from monelyth_engine.db.models import Category, CategorySource, Transaction
from monelyth_engine.db.rules import RuleMatchType, create_rule
from monelyth_engine.db.transactions import get_transaction, update_transaction
from tests.categorize.conftest import item
from tests.db.conftest import ImportStatement, raw


class FakeTier:
    """Answers descriptions it knows, with the given confidence, and records what it saw."""

    def __init__(
        self,
        answers: dict[str, int] | None = None,
        *,
        source: CategorySource = CategorySource.LLM,
        confidence: float = 0.95,
        fail: bool = False,
        wrong_length: bool = False,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self._answers = answers or {}
        self._source = source
        self._confidence = confidence
        self._fail = fail
        self._wrong_length = wrong_length
        self._on_call = on_call
        self.seen: list[list[str]] = []

    @property
    def source(self) -> CategorySource:
        return self._source

    def suggest(
        self, items: Sequence[CategorizationInput], categories: Sequence[Category]
    ) -> list[Suggestion | None]:
        self.seen.append([entry.description for entry in items])
        if self._on_call is not None:
            self._on_call()
        if self._fail:
            raise RuntimeError("model file missing")
        answers: list[Suggestion | None] = [
            None
            if entry.description not in self._answers
            else Suggestion(self._answers[entry.description], self._source, self._confidence)
            for entry in items
        ]
        return answers[:-1] if self._wrong_length else answers


class FakePrePass:
    def __init__(self, action: Callable[[sqlite3.Connection], None]) -> None:
        self._action = action
        self.runs = 0

    @property
    def name(self) -> str:
        return "Transfer detection"

    def run(self, conn: sqlite3.Connection) -> None:
        self.runs += 1
        self._action(conn)


def _by_description(db: sqlite3.Connection) -> dict[str, Transaction]:
    rows = db.execute("SELECT id FROM transactions").fetchall()
    return {tx.description_raw: tx for tx in (get_transaction(db, row["id"]) for row in rows)}


def _run(
    db: sqlite3.Connection,
    scope: RunScope = UNPROCESSED,
    *tiers: FakeTier,
    pre_passes: Sequence[FakePrePass] = (),
    on_progress: ProgressCallback | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunResult:
    extensions = PipelineExtensions(
        optional_tiers=(lambda _conn: list(tiers)) if tiers else None,
        pre_passes=tuple(pre_passes),
    )
    return run_categorization(
        db, scope, extensions=extensions, on_progress=on_progress, should_stop=should_stop
    )


@pytest.fixture
def seeded(import_statement: ImportStatement) -> None:
    import_statement(
        [
            raw(1, -1650, "UBER* EATS PENDING"),
            raw(2, -2318, "UBER *TRIP"),
            raw(3, -999, "MYSTERY SHOP 123"),
            raw(4, 250_000, "PAYROLL ACME CORP"),
        ],
        file_label="sept",
        merchants=["Uber Eats", "Uber", "Mystery Shop", "Payroll Acme Corp"],
    )


def test_rules_answer_and_unanswered_go_to_review(
    db: sqlite3.Connection, seeded: None, categories: dict[str, Category]
) -> None:
    result = _run(db)

    txs = _by_description(db)
    eats = txs["UBER* EATS PENDING"]
    assert (eats.category_id, eats.category_source, eats.confidence, eats.needs_review) == (
        categories["Dining Out"].id,
        CategorySource.RULE,
        1.0,
        False,
    )
    assert txs["UBER *TRIP"].category_id == categories["Rideshare"].id
    assert txs["PAYROLL ACME CORP"].category_id == categories["Salary"].id
    mystery = txs["MYSTERY SHOP 123"]
    assert (mystery.category_id, mystery.category_source, mystery.needs_review) == (
        None,
        None,
        True,
    )
    assert (result.total, result.processed, result.needs_review) == (4, 4, 1)
    assert result.answered == {CategorySource.RULE: 3}
    assert result.problems == []
    assert not result.cancelled


def test_never_touches_what_the_user_set_or_a_linked_transfer(
    db: sqlite3.Connection, seeded: None, categories: dict[str, Category]
) -> None:
    txs = _by_description(db)
    update_transaction(db, txs["UBER *TRIP"].id, category_id=categories["Transport"].id)
    db.execute(
        "UPDATE transactions SET transfer_group = 'g1' WHERE id = ?",
        (txs["PAYROLL ACME CORP"].id,),
    )

    result = _run(db, AUTOMATIC)

    after = _by_description(db)
    assert after["UBER *TRIP"] == get_transaction(db, txs["UBER *TRIP"].id)
    assert after["UBER *TRIP"].category_source is CategorySource.USER
    assert after["UBER *TRIP"].category_id == categories["Transport"].id
    assert after["PAYROLL ACME CORP"].category_id is None
    assert result.total == 2


def test_scopes_pick_which_transactions_a_run_looks_at(
    db: sqlite3.Connection, seeded: None, categories: dict[str, Category]
) -> None:
    _run(db)
    tier = FakeTier({"MYSTERY SHOP 123": categories["Shopping"].id})

    assert _run(db, UNPROCESSED, tier).total == 0
    assert tier.seen == []
    assert _run(db, UNCATEGORIZED, tier).total == 1
    assert tier.seen == [["MYSTERY SHOP 123"]]
    eats = _by_description(db)["UBER* EATS PENDING"]
    assert _run(db, RunScope(transaction_ids=frozenset({eats.id, 9999}))).total == 1
    assert _run(db, AUTOMATIC).total == 4


def test_optional_tiers_follow_memory_and_rules(
    db: sqlite3.Connection, seeded: None, categories: dict[str, Category]
) -> None:
    tier = FakeTier(
        {"MYSTERY SHOP 123": categories["Shopping"].id, "UBER *TRIP": categories["Other"].id}
    )

    _run(db, UNPROCESSED, tier)

    # Rules answered the others; the tier only saw what they left.
    assert tier.seen == [["MYSTERY SHOP 123"]]
    mystery = _by_description(db)["MYSTERY SHOP 123"]
    assert (mystery.category_id, mystery.category_source, mystery.confidence) == (
        categories["Shopping"].id,
        CategorySource.LLM,
        0.95,
    )


def test_confident_model_answers_are_remembered_uncertain_ones_are_not(
    db: sqlite3.Connection, import_statement: ImportStatement, categories: dict[str, Category]
) -> None:
    import_statement(
        [raw(1, -100, "SURE THING"), raw(2, -100, "MAYBE THING")],
        file_label="a",
        merchants=["Sure Thing", "Maybe Thing"],
    )
    shopping = categories["Shopping"].id
    _run(db, UNPROCESSED, FakeTier({"SURE THING": shopping}, confidence=0.9))
    _run(db, UNCATEGORIZED, FakeTier({"MAYBE THING": shopping}, confidence=0.5))

    maybe = _by_description(db)["MAYBE THING"]
    assert (maybe.category_id, maybe.needs_review) == (shopping, True)
    memory = load_memory(db)
    assert set(memory) == {"sure thing"}
    assert memory["sure thing"].source is CategorySource.LLM


def test_user_memory_beats_rules_which_beat_learned_memory(
    db: sqlite3.Connection, seeded: None, categories: dict[str, Category]
) -> None:
    remember(db, "uber", category_id=categories["Transport"].id, source=CategorySource.USER)
    remember(db, "uber eats", category_id=categories["Groceries"].id, source=CategorySource.LLM)
    remember(db, "mystery shop", category_id=categories["Shopping"].id, source=CategorySource.LLM)

    _run(db)

    txs = _by_description(db)
    assert txs["UBER *TRIP"].category_id == categories["Transport"].id
    assert txs["UBER *TRIP"].category_source is CategorySource.MEMORY
    assert txs["UBER* EATS PENDING"].category_id == categories["Dining Out"].id
    assert txs["MYSTERY SHOP 123"].category_id == categories["Shopping"].id
    assert txs["MYSTERY SHOP 123"].category_source is CategorySource.MEMORY


def test_a_user_rule_beats_the_default_rules(
    db: sqlite3.Connection, seeded: None, categories: dict[str, Category]
) -> None:
    create_rule(
        db,
        pattern="uber",
        match_type=RuleMatchType.CONTAINS,
        category_id=categories["Transport"].id,
        priority=0,
    )

    _run(db)

    # "uber eats" has a higher priority among the defaults, but yours always come first.
    assert _by_description(db)["UBER* EATS PENDING"].category_id == categories["Transport"].id


def test_a_failing_tier_is_skipped_and_reported(
    db: sqlite3.Connection,
    import_statement: ImportStatement,
    categories: dict[str, Category],
    caplog: pytest.LogCaptureFixture,
) -> None:
    import_statement([raw(1, -100, f"THING {n}") for n in range(BATCH_SIZE + 1)], file_label="many")
    broken = FakeTier(source=CategorySource.CLASSIFIER, fail=True)
    backup = FakeTier({"THING 0": categories["Other"].id})

    result = _run(db, UNPROCESSED, broken, backup)

    # Tried on the first batch only, then skipped; the next tier still answered.
    assert len(broken.seen) == 1
    assert len(backup.seen) == 2
    assert _by_description(db)["THING 0"].category_id == categories["Other"].id
    assert result.problems == ["The classifier"]
    assert "Categorization tier The classifier failed" in caplog.text


def test_a_failing_tier_factory_or_pre_pass_is_reported(
    db: sqlite3.Connection, seeded: None
) -> None:
    def broken_factory(_conn: sqlite3.Connection) -> list[FakeTier]:
        raise OSError("model folder unreadable")

    def broken_pre_pass(_conn: sqlite3.Connection) -> None:
        raise RuntimeError("bug")

    result = run_categorization(
        db,
        UNPROCESSED,
        extensions=PipelineExtensions(
            optional_tiers=broken_factory, pre_passes=(FakePrePass(broken_pre_pass),)
        ),
    )

    assert result.problems == ["Transfer detection", "The optional categorization steps"]
    assert result.answered == {CategorySource.RULE: 3}


def test_pre_passes_run_first_and_the_tiers_skip_what_they_linked(
    db: sqlite3.Connection, seeded: None, categories: dict[str, Category]
) -> None:
    transfers = categories["Transfers"].id

    def link(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE transactions SET transfer_group = 't1', category_id = ?, "
            "category_source = 'rule', confidence = 1.0 WHERE description_raw = 'UBER *TRIP'",
            (transfers,),
        )

    pre_pass = FakePrePass(link)

    result = _run(db, pre_passes=[pre_pass])

    assert pre_pass.runs == 1
    assert result.total == 3
    assert _by_description(db)["UBER *TRIP"].category_id == transfers


def test_a_tier_breaking_the_contract_is_skipped(
    db: sqlite3.Connection, seeded: None, categories: dict[str, Category]
) -> None:
    result = _run(db, UNPROCESSED, FakeTier({"MYSTERY SHOP 123": 1}, wrong_length=True))

    assert result.problems == ["The local AI model"]
    assert _by_description(db)["MYSTERY SHOP 123"].category_id is None


def test_stopping_keeps_the_batches_already_stored(
    db: sqlite3.Connection, import_statement: ImportStatement
) -> None:
    import_statement(
        [raw(1, -100, f"NETFLIX {n}") for n in range(BATCH_SIZE * 2)], file_label="many"
    )
    progress: list[tuple[int, int]] = []

    result = _run(
        db,
        on_progress=lambda done, total: progress.append((done, total)),
        should_stop=lambda: len(progress) > 1,
    )

    assert result.cancelled
    assert progress == [(0, BATCH_SIZE * 2), (BATCH_SIZE, BATCH_SIZE * 2)]
    stored = db.execute("SELECT COUNT(*) FROM transactions WHERE category_id IS NOT NULL")
    assert stored.fetchone()[0] == BATCH_SIZE


def test_a_choice_the_user_makes_during_a_run_stands(
    db: sqlite3.Connection, db_path: Path, seeded: None, categories: dict[str, Category]
) -> None:
    mystery = _by_description(db)["MYSTERY SHOP 123"]

    def user_edits_meanwhile() -> None:
        # Another connection, as a request handler would use, while the tier is thinking.
        other = connect(db_path)
        try:
            update_transaction(other, mystery.id, category_id=categories["Gifts & Donations"].id)
        finally:
            other.close()

    _run(
        db,
        UNPROCESSED,
        FakeTier({"MYSTERY SHOP 123": categories["Shopping"].id}, on_call=user_edits_meanwhile),
    )

    after = get_transaction(db, mystery.id)
    assert (after.category_id, after.category_source) == (
        categories["Gifts & Donations"].id,
        CategorySource.USER,
    )
    assert "mystery shop" not in load_memory(db)


def test_tier_runner_drops_suggestions_for_unknown_categories(
    categories: dict[str, Category], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    first = FakeTier({"A": 999})
    second = FakeTier({"A": categories["Other"].id})
    runner = TierRunner([first, second], list(categories.values()))

    [answer] = runner.suggest([item("A")])

    assert answer == Suggestion(categories["Other"].id, CategorySource.LLM, 0.95)
    assert "category 999, which does not exist" in caplog.text
    assert runner.failed == ()


def test_tier_runner_answers_nothing_for_no_items(categories: dict[str, Category]) -> None:
    tier = FakeTier()

    assert TierRunner([tier], list(categories.values())).suggest([]) == []
    assert tier.seen == []
