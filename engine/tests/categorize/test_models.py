from __future__ import annotations

import pytest

from monelyth_engine.categorize.models import REVIEW_THRESHOLD, Suggestion
from monelyth_engine.db.models import CategorySource


def test_confident_suggestion_needs_no_review() -> None:
    suggestion = Suggestion(category_id=5, source=CategorySource.RULE, confidence=1.0)

    assert suggestion.needs_review is False


def test_uncertain_suggestion_needs_review() -> None:
    suggestion = Suggestion(
        category_id=5, source=CategorySource.CLASSIFIER, confidence=REVIEW_THRESHOLD - 0.01
    )

    assert suggestion.needs_review is True


@pytest.mark.parametrize("confidence", [-0.1, 1.01])
def test_confidence_must_be_a_probability(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        Suggestion(category_id=5, source=CategorySource.LLM, confidence=confidence)


def test_tiers_cannot_claim_to_be_the_user() -> None:
    with pytest.raises(ValueError, match="user"):
        Suggestion(category_id=5, source=CategorySource.USER, confidence=1.0)
