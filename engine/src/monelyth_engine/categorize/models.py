"""The contract between the categorization pipeline and its tiers.

Every tier (merchant memory, rules, classifier, LLM) is a :class:`Categorizer`. The pipeline
asks the tiers in order; each answers the transactions it can and passes the rest (``None``)
to the next one. Cheap, certain tiers come first, so the expensive ones only see what is left:

    merchant memory -> rules -> classifier -> LLM -> review queue

A tier never writes to the database and never overrides a category the user chose; the
pipeline does all writing and only ever touches transactions without a user-set category.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from monelyth_engine.db.models import Category, CategorySource

REVIEW_THRESHOLD: Final = 0.80
"""Suggestions below this confidence are stored but flagged ``needs_review``.

A starting point from PLAN.md 3.7, to be tuned with the evaluation script: higher means fewer
wrong categories slip through, but more transactions land in the review queue."""


@dataclass(frozen=True, slots=True)
class CategorizationInput:
    """What a tier may look at to categorize one stored transaction."""

    transaction_id: int
    account_id: int
    posted_date: datetime.date
    amount_cents: int
    """Negative = money out, positive = money in."""
    description: str
    """The bank's text, exactly as imported."""
    merchant: str | None
    """The cleaned merchant name, when merchant cleaning found one."""


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A tier's answer for one transaction."""

    category_id: int
    source: CategorySource
    """Which tier answered; stored as the transaction's ``category_source``."""
    confidence: float
    """0..1. Memory and rules answer with 1.0; a classifier or LLM with its own estimate."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {self.confidence}")
        if self.source is CategorySource.USER:
            raise ValueError("tiers never answer as the user")

    @property
    def needs_review(self) -> bool:
        return self.confidence < REVIEW_THRESHOLD


class Categorizer(Protocol):
    """One tier of the pipeline."""

    @property
    def source(self) -> CategorySource:
        """The ``category_source`` this tier's suggestions carry."""
        ...

    def suggest(
        self, items: Sequence[CategorizationInput], categories: Sequence[Category]
    ) -> list[Suggestion | None]:
        """Answer each item, in order: a suggestion, or ``None`` to leave it to the next tier.

        ``categories`` lists every category the answer may use. The returned list has exactly
        one entry per item. Must not raise for an individual item it can't answer; raising
        means the whole tier failed (e.g. a model file is missing) and the pipeline skips it.
        """
        ...
