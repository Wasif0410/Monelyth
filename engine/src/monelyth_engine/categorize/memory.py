"""Tier 1: merchant memory ("Blue Bottle is always Coffee").

The pipeline asks memory twice, because who wrote an entry decides how much it counts
(PLAN.md 3.2): entries from the user's own corrections come before every rule, while entries
the classifier or the LLM wrote come after the rules, so a rule the user adds beats a guess a
model once made. :func:`user_memory` and :func:`learned_memory` build the two tiers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from monelyth_engine.categorize.models import CategorizationInput, Suggestion
from monelyth_engine.db.memory import MemoryEntry
from monelyth_engine.db.models import Category, CategorySource
from monelyth_engine.normalize import merchant_key


def memory_key(merchant: str | None) -> str | None:
    """The key a transaction's merchant is remembered by, or ``None`` if it has none."""
    if merchant is None:
        return None
    return merchant_key(merchant) or None


class MerchantMemoryCategorizer:
    """Answers with the remembered category of the merchant, with full confidence.

    Only entries written by one of ``sources`` count; the rest are left to other tiers.
    """

    def __init__(
        self, entries: Mapping[str, MemoryEntry], *, sources: frozenset[CategorySource]
    ) -> None:
        self._categories = {
            key: entry.category_id for key, entry in entries.items() if entry.source in sources
        }

    @property
    def source(self) -> CategorySource:
        return CategorySource.MEMORY

    def suggest(
        self, items: Sequence[CategorizationInput], categories: Sequence[Category]
    ) -> list[Suggestion | None]:
        del categories  # Memory names its category itself.
        return [self._suggest(item) for item in items]

    def _suggest(self, item: CategorizationInput) -> Suggestion | None:
        key = memory_key(item.merchant)
        category_id = None if key is None else self._categories.get(key)
        if category_id is None:
            return None
        return Suggestion(category_id=category_id, source=CategorySource.MEMORY, confidence=1.0)


def user_memory(entries: Mapping[str, MemoryEntry]) -> MerchantMemoryCategorizer:
    """What the user taught by correcting a category: beats everything else."""
    return MerchantMemoryCategorizer(entries, sources=frozenset({CategorySource.USER}))


def learned_memory(entries: Mapping[str, MemoryEntry]) -> MerchantMemoryCategorizer:
    """What the classifier or LLM answered confidently before: beaten by every rule."""
    return MerchantMemoryCategorizer(
        entries, sources=frozenset({CategorySource.CLASSIFIER, CategorySource.LLM})
    )
