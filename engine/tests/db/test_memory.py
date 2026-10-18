from __future__ import annotations

import datetime
import sqlite3

import pytest

from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.memory import MemoryEntry, load_memory, remember
from monelyth_engine.db.models import CategorySource

EARLIER = datetime.datetime(2026, 10, 1, 9, 30, tzinfo=datetime.UTC)
LATER = datetime.datetime(
    2026, 10, 2, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-4))
)


@pytest.fixture
def ids(db: sqlite3.Connection) -> dict[str, int]:
    return {category.name: category.id for category in list_categories(db)}


def test_remember_and_load(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    assert remember(
        db, "blue bottle", category_id=ids["Coffee"], source=CategorySource.USER, now=LATER
    )

    assert load_memory(db) == {
        "blue bottle": MemoryEntry(
            "blue bottle",
            ids["Coffee"],
            CategorySource.USER,
            # Stored in UTC.
            datetime.datetime(2026, 10, 2, 16, 0, tzinfo=datetime.UTC),
        )
    }


def test_the_user_overrides_anything(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    remember(db, "costco", category_id=ids["Shopping"], source=CategorySource.LLM, now=EARLIER)
    remember(db, "costco", category_id=ids["Groceries"], source=CategorySource.USER, now=LATER)
    assert remember(db, "costco", category_id=ids["Other"], source=CategorySource.USER)

    entry = load_memory(db)["costco"]
    assert (entry.category_id, entry.source) == (ids["Other"], CategorySource.USER)


def test_a_model_never_overrides_the_user(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    remember(db, "costco", category_id=ids["Groceries"], source=CategorySource.USER, now=EARLIER)

    written = remember(db, "costco", category_id=ids["Shopping"], source=CategorySource.LLM)

    assert written is False
    entry = load_memory(db)["costco"]
    assert (entry.category_id, entry.source, entry.updated_at) == (
        ids["Groceries"],
        CategorySource.USER,
        EARLIER,
    )


def test_models_override_each_other(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    remember(db, "ikea", category_id=ids["Other"], source=CategorySource.CLASSIFIER, now=EARLIER)

    assert remember(db, "ikea", category_id=ids["Shopping"], source=CategorySource.LLM, now=LATER)
    assert load_memory(db)["ikea"].source is CategorySource.LLM


@pytest.mark.parametrize(
    ("key", "source", "now", "message"),
    [
        ("", CategorySource.USER, EARLIER, "empty"),
        ("x", CategorySource.RULE, EARLIER, "does not write merchant memory"),
        ("x", CategorySource.MEMORY, EARLIER, "does not write merchant memory"),
        ("x", CategorySource.USER, datetime.datetime(2026, 10, 1), "timezone-aware"),
    ],
)
def test_remember_refuses_bad_input(
    db: sqlite3.Connection,
    ids: dict[str, int],
    key: str,
    source: CategorySource,
    now: datetime.datetime,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        remember(db, key, category_id=ids["Other"], source=source, now=now)


def test_remember_refuses_an_unknown_category(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        remember(db, "x", category_id=999, source=CategorySource.USER)
