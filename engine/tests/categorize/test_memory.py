from __future__ import annotations

import datetime

import pytest

from monelyth_engine.categorize.memory import learned_memory, memory_key, user_memory
from monelyth_engine.categorize.models import Suggestion
from monelyth_engine.db.memory import MemoryEntry
from monelyth_engine.db.models import CategorySource
from tests.categorize.conftest import item

WHEN = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


def _entries(*entries: tuple[str, int, CategorySource]) -> dict[str, MemoryEntry]:
    return {key: MemoryEntry(key, category, source, WHEN) for key, category, source in entries}


@pytest.mark.parametrize(
    ("merchant", "key"),
    [("Blue Bottle", "blue bottle"), ("BLUE-BOTTLE", "blue bottle"), ("--", None), (None, None)],
)
def test_memory_key(merchant: str | None, key: str | None) -> None:
    assert memory_key(merchant) == key


def test_each_memory_tier_answers_only_from_its_own_sources() -> None:
    entries = _entries(
        ("blue bottle", 7, CategorySource.USER),
        ("costco", 11, CategorySource.LLM),
        ("ikea", 11, CategorySource.CLASSIFIER),
    )
    items = [
        item("SQ *BLUE BOTTLE", "Blue  Bottle"),
        item("COSTCO", "Costco"),
        item("IKEA", "IKEA"),
    ]
    found = Suggestion(category_id=7, source=CategorySource.MEMORY, confidence=1.0)
    learned = Suggestion(category_id=11, source=CategorySource.MEMORY, confidence=1.0)

    assert user_memory(entries).suggest(items, []) == [found, None, None]
    assert learned_memory(entries).suggest(items, []) == [None, learned, learned]
    assert user_memory(entries).source is CategorySource.MEMORY


def test_memory_needs_a_merchant_name() -> None:
    entries = _entries(("blue bottle", 7, CategorySource.USER))

    # The description alone is not looked up: memory is about cleaned merchant names.
    assert user_memory(entries).suggest([item("BLUE BOTTLE", None)], []) == [None]
