"""Smoke test against a real local LLM, run only when one is configured and answering.

Set MONELYTH_LLM_URL and MONELYTH_LLM_MODEL (for example ``http://127.0.0.1:11434/v1`` and
``qwen3:4b`` with Ollama running) to include it; otherwise it is skipped.
"""

from __future__ import annotations

import datetime

import pytest

from monelyth_engine.categorize.llm_tier import create_llm_categorizer
from monelyth_engine.categorize.models import CategorizationInput
from monelyth_engine.db.models import Category, CategoryKind, CategorySource
from monelyth_engine.llm.config import URL_ENV_VAR


def test_real_model_categorizes_an_obvious_merchant() -> None:
    tier = create_llm_categorizer()
    if tier is None:
        pytest.skip(f"no local LLM configured and answering (set {URL_ENV_VAR} to run this)")
    categories = [
        Category(id=1, name="Salary", kind=CategoryKind.INCOME, parent_id=None),
        Category(id=2, name="Groceries", kind=CategoryKind.EXPENSE, parent_id=None),
        Category(id=3, name="Subscriptions", kind=CategoryKind.EXPENSE, parent_id=None),
        Category(id=4, name="Transfers", kind=CategoryKind.TRANSFER, parent_id=None),
    ]
    item = CategorizationInput(
        transaction_id=1,
        account_id=1,
        posted_date=datetime.date(2026, 10, 1),
        amount_cents=-1799,
        description="NETFLIX.COM 866-579-7172 CA",
        merchant="Netflix",
    )

    try:
        [suggestion] = tier.suggest([item], categories)
    finally:
        tier.close()

    assert suggestion is not None
    assert suggestion.source is CategorySource.LLM
    assert suggestion.category_id == 3
