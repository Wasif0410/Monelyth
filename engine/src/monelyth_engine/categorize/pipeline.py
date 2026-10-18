"""Running the tiers over stored transactions and saving what they answer.

:class:`TierRunner` asks the tiers for a list of items and knows nothing about the database,
so the evaluation script uses it directly. :func:`run_categorization` wraps it for the stored
transactions: it picks the ones a run should look at, asks the tiers in batches and stores
each batch in one database transaction, so stopping between batches never leaves a batch half
written.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from monelyth_engine.categorize.memory import memory_key
from monelyth_engine.categorize.models import CategorizationInput, Categorizer, Suggestion
from monelyth_engine.categorize.tiers import PipelineExtensions, core_tiers
from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.categorization import (
    CategorizationRow,
    CategorizationState,
    CategoryAssignment,
    assign_categories,
    categorization_rows,
    categorization_states,
)
from monelyth_engine.db.memory import load_memory, remember
from monelyth_engine.db.models import Category, CategorySource
from monelyth_engine.db.rules import list_rules

BATCH_SIZE: Final = 64
"""Transactions asked and stored together; small enough that stopping is quick even when a
slow tier (the LLM) answers them."""

LEARNING_SOURCES: Final = frozenset({CategorySource.CLASSIFIER, CategorySource.LLM})
"""Tiers whose confident answers are saved to merchant memory, so each merchant costs a model
call once. Uncertain answers are not saved: memory answers with full confidence."""

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunScope:
    """Which of the transactions automatic categorization may change a run looks at.

    Scopes combine (:meth:`merge`), so several requests waiting for the worker become one run.
    """

    unprocessed: bool = False
    """Stored but never looked at, e.g. just imported."""
    uncategorized: bool = False
    """Without a category, including those no tier could answer before."""
    automatic: bool = False
    """Every one, re-asking the tiers even where they answered before."""
    transaction_ids: frozenset[int] = frozenset()
    """These, e.g. the ones a changed rule matches."""

    def merge(self, other: RunScope) -> RunScope:
        return RunScope(
            unprocessed=self.unprocessed or other.unprocessed,
            uncategorized=self.uncategorized or other.uncategorized,
            automatic=self.automatic or other.automatic,
            transaction_ids=self.transaction_ids | other.transaction_ids,
        )

    def includes(self, state: CategorizationState) -> bool:
        return (
            self.automatic
            or (self.uncategorized and state.category_id is None)
            or (self.unprocessed and state.unprocessed)
            or state.id in self.transaction_ids
        )


UNPROCESSED: Final = RunScope(unprocessed=True)
UNCATEGORIZED: Final = RunScope(uncategorized=True)
AUTOMATIC: Final = RunScope(automatic=True)


def describe_tier(tier: Categorizer) -> str:
    """How a tier is named in logs and in problems shown to the user."""
    return _SOURCE_NAMES.get(tier.source, tier.source.value)


_SOURCE_NAMES: Final = {
    CategorySource.MEMORY: "Merchant memory",
    CategorySource.RULE: "Rules",
    CategorySource.CLASSIFIER: "The classifier",
    CategorySource.LLM: "The local AI model",
}


class TierRunner:
    """Asks tiers in order; each answers what it can and passes the rest to the next.

    One runner serves one run. A tier that raises, or breaks the contract by answering with the
    wrong number of items, is logged and skipped for the rest of the run. A single suggestion
    naming a category that doesn't exist is dropped, and the item passes to the next tier.
    """

    def __init__(self, tiers: Sequence[Categorizer], categories: Sequence[Category]) -> None:
        self._tiers = tuple(tiers)
        self._categories = tuple(categories)
        self._category_ids = frozenset(category.id for category in categories)
        self._failed: list[Categorizer] = []

    @property
    def failed(self) -> tuple[Categorizer, ...]:
        """The tiers skipped because they failed, in the order they failed."""
        return tuple(self._failed)

    def suggest(self, items: Sequence[CategorizationInput]) -> list[Suggestion | None]:
        """One answer per item, in order: the first tier's suggestion, or ``None``."""
        answers: list[Suggestion | None] = [None] * len(items)
        pending = list(range(len(items)))
        for tier in self._tiers:
            if not pending:
                break
            if tier in self._failed:
                continue
            suggestions = self._ask(tier, [items[index] for index in pending])
            if suggestions is None:
                continue
            unanswered: list[int] = []
            for index, suggestion in zip(pending, suggestions, strict=True):
                if suggestion is not None and suggestion.category_id not in self._category_ids:
                    logger.warning(
                        "%s suggested category %d, which does not exist; ignoring it",
                        describe_tier(tier),
                        suggestion.category_id,
                    )
                    suggestion = None
                if suggestion is None:
                    unanswered.append(index)
                else:
                    answers[index] = suggestion
            pending = unanswered
        return answers

    def _ask(
        self, tier: Categorizer, items: list[CategorizationInput]
    ) -> list[Suggestion | None] | None:
        try:
            suggestions = tier.suggest(items, self._categories)
            if len(suggestions) != len(items):
                raise RuntimeError(
                    f"answered {len(suggestions)} items when asked about {len(items)}"
                )
        except Exception:
            logger.exception(
                "Categorization tier %s failed; skipping it for the rest of this run",
                describe_tier(tier),
            )
            self._failed.append(tier)
            return None
        return suggestions


@dataclass(slots=True)
class RunResult:
    total: int = 0
    """How many transactions the run set out to look at."""
    processed: int = 0
    answered: Counter[CategorySource] = field(default_factory=Counter[CategorySource])
    """How many each tier answered (whether or not the answer needs review)."""
    needs_review: int = 0
    """Stored with ``needs_review``: unanswered, or answered with low confidence."""
    problems: list[str] = field(default_factory=list[str])
    """Parts that failed and were skipped, written for the user."""
    cancelled: bool = False


ProgressCallback = Callable[[int, int], None]
"""Called with (processed, total) when a run starts and after each batch is stored."""


def run_categorization(
    conn: sqlite3.Connection,
    scope: RunScope,
    *,
    extensions: PipelineExtensions,
    on_progress: ProgressCallback | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunResult:
    """Categorize the stored transactions in ``scope`` and save the answers.

    Only transactions automatic categorization may change are looked at (never one the user
    categorized, never a linked transfer). Each gets the first tier's answer, its source and
    confidence, and ``needs_review`` when that confidence is low; one that no tier answers is
    left without a category and flagged for review.

    Args:
        should_stop: checked before each batch; when it returns true the run ends early.
            Batches already stored stay stored.

    Raises:
        sqlite3.Error: if the database can't be read or written. Tier failures don't raise;
            they are logged and listed in :attr:`RunResult.problems`.
    """
    result = RunResult()
    for pre_pass in extensions.pre_passes:
        try:
            pre_pass.run(conn)
        except Exception:
            logger.exception("Categorization pre-pass %r failed; skipping it", pre_pass.name)
            result.problems.append(pre_pass.name)

    categories = list_categories(conn)
    memory = load_memory(conn)
    tiers = core_tiers(memory, list_rules(conn))
    if extensions.optional_tiers is not None:
        try:
            tiers.extend(extensions.optional_tiers(conn))
        except Exception:
            logger.exception("Could not set up the optional categorization tiers")
            result.problems.append("The optional categorization steps")
    runner = TierRunner(tiers, categories)

    ids = [state.id for state in categorization_states(conn) if scope.includes(state)]
    result.total = len(ids)
    if on_progress is not None:
        on_progress(0, result.total)
    for start in range(0, len(ids), BATCH_SIZE):
        if should_stop is not None and should_stop():
            result.cancelled = True
            break
        rows = categorization_rows(conn, ids[start : start + BATCH_SIZE])
        suggestions = runner.suggest([_input(row) for row in rows])
        _store(conn, rows, suggestions, result)
        result.processed = min(start + BATCH_SIZE, len(ids))
        if on_progress is not None:
            on_progress(result.processed, result.total)

    result.problems.extend(describe_tier(tier) for tier in runner.failed)
    logger.info(
        "Categorized %d of %d transactions (%s); %d need review%s",
        result.processed,
        result.total,
        ", ".join(f"{source.value}: {n}" for source, n in result.answered.items()) or "none",
        result.needs_review,
        "; stopped early" if result.cancelled else "",
    )
    return result


def _input(row: CategorizationRow) -> CategorizationInput:
    return CategorizationInput(
        transaction_id=row.id,
        account_id=row.account_id,
        posted_date=row.posted_date,
        amount_cents=row.amount_cents,
        description=row.description_raw,
        merchant=row.merchant,
    )


def _store(
    conn: sqlite3.Connection,
    rows: Sequence[CategorizationRow],
    suggestions: Sequence[Suggestion | None],
    result: RunResult,
) -> None:
    assignments = [
        CategoryAssignment(row.id, None, None, None, needs_review=True)
        if suggestion is None
        else CategoryAssignment(
            row.id,
            suggestion.category_id,
            suggestion.source,
            suggestion.confidence,
            needs_review=suggestion.needs_review,
        )
        for row, suggestion in zip(rows, suggestions, strict=True)
    ]
    now = datetime.datetime.now(datetime.UTC)
    with atomic(conn):
        updated = assign_categories(conn, assignments)
        for row, suggestion in zip(rows, suggestions, strict=True):
            if row.id not in updated:
                continue
            if suggestion is None or suggestion.needs_review:
                result.needs_review += 1
            if suggestion is None:
                continue
            result.answered[suggestion.source] += 1
            key = memory_key(row.merchant)
            if (
                key is not None
                and suggestion.source in LEARNING_SOURCES
                and not suggestion.needs_review
            ):
                remember(
                    conn,
                    key,
                    category_id=suggestion.category_id,
                    source=suggestion.source,
                    now=now,
                )
