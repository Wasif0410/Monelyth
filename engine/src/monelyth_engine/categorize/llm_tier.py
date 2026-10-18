"""Tier 4: ask a local LLM about the transactions every earlier tier passed on.

The model gets the category list and one transaction at a time, and must answer with JSON
matching a schema whose ``category`` is an enum of the exact category names, so it can only
pick a real category. The description is the bank's text and could contain anything, which is
another reason the answer is constrained: the worst a strange description can cause is a wrong
category, never an unexpected action.

The tier is optional. :func:`create_llm_categorizer` returns ``None`` when no LLM is set up or
the server isn't running, and the app works without it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Final

from pydantic import BaseModel, StrictBool, StrictStr, ValidationError

from monelyth_engine.categorize.models import CategorizationInput, Suggestion
from monelyth_engine.db.models import Category, CategorySource
from monelyth_engine.llm.client import ChatMessage, JsonSchema, LLMClient
from monelyth_engine.llm.config import load_llm_config
from monelyth_engine.llm.errors import LLMConfigError, LLMResponseError, LLMUnavailableError

logger = logging.getLogger(__name__)

CONFIDENT: Final = 0.85
"""Confidence stored when the model says it is sure: just above ``REVIEW_THRESHOLD`` (0.80),
so the answer is accepted without review, but below the 1.0 of memory and rules, which are
certain. A model's own "I'm sure" is poorly calibrated, so it earns no more than that; if the
eval shows confident LLM answers are often wrong, raising the threshold past 0.85 sends every
LLM answer to review without touching this tier."""

UNSURE: Final = 0.5
"""Confidence stored when the model says it is guessing: well below the threshold, so the
transaction lands in the review queue, with the model's guess pre-selected for the user."""

DEFAULT_MAX_CALLS_PER_RUN: Final = 200
"""How many LLM requests one run may make. A first import can bring hundreds of merchants the
earlier tiers don't know; at a few seconds per request on a laptop CPU this bounds a run to
minutes. Transactions past the cap are left for the review queue or the next run."""

MAX_ANSWER_TOKENS: Final = 100
"""The answer is one short JSON object; the cap only stops a misbehaving model early."""

_SYSTEM_PROMPT: Final = (
    "You sort bank transactions into budget categories for a personal finance app. "
    "Pick the one category from the list that best fits the transaction and answer with its "
    'exact name. Set "confident" to true only when the merchant is clearly recognizable and '
    "the category clearly fits; set it to false when the description is ambiguous or you are "
    "guessing. Money in is usually income, a refund or a transfer; money out is usually an "
    "expense or a transfer."
)


class LLMCategorizer:
    """A :class:`~monelyth_engine.categorize.models.Categorizer` backed by a local LLM.

    Transactions are sent one at a time, in order (a local server runs one request at a time
    anyway). Within a run, transactions from the same merchant share one request.
    """

    def __init__(
        self, client: LLMClient, *, max_calls_per_run: int = DEFAULT_MAX_CALLS_PER_RUN
    ) -> None:
        if max_calls_per_run < 1:
            raise ValueError(f"max_calls_per_run must be at least 1, got {max_calls_per_run}")
        self._client = client
        self._max_calls_per_run = max_calls_per_run

    @property
    def source(self) -> CategorySource:
        return CategorySource.LLM

    def close(self) -> None:
        """Close the connection to the LLM server."""
        self._client.close()

    def suggest(
        self, items: Sequence[CategorizationInput], categories: Sequence[Category]
    ) -> list[Suggestion | None]:
        """Ask the LLM about each item; ``None`` where it gave no usable answer.

        Raises:
            LLMUnavailableError: the server failed on the run's first request. If it fails
                later, the answers so far are kept and the remaining items are ``None``.
        """
        results: list[Suggestion | None] = [None] * len(items)
        if not items or not categories:
            return results

        schema = _answer_schema(categories)
        categories_text = _categories_text(categories)
        by_name = {category.name.casefold(): category for category in categories}
        # Each merchant's answer in this run, so each merchant costs one request.
        answers: dict[str, Suggestion | None] = {}
        calls = 0
        over_cap = 0

        for index, item in enumerate(items):
            key = _merchant_key(item)
            if key not in answers:
                if calls == self._max_calls_per_run:
                    over_cap += 1
                    continue
                calls += 1
                try:
                    answers[key] = self._ask(item, categories_text, schema, by_name)
                except LLMUnavailableError:
                    if calls == 1:
                        raise
                    logger.warning(
                        "Local AI server stopped answering after %d requests; "
                        "leaving the remaining transactions uncategorized",
                        calls - 1,
                    )
                    break
            results[index] = answers[key]

        if over_cap:
            logger.info(
                "Local AI request limit (%d) reached; %d transactions left for the next run",
                self._max_calls_per_run,
                over_cap,
            )
        return results

    def _ask(
        self,
        item: CategorizationInput,
        categories_text: str,
        schema: JsonSchema,
        by_name: Mapping[str, Category],
    ) -> Suggestion | None:
        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=_user_prompt(item, categories_text)),
        ]
        try:
            reply = self._client.complete_json(
                messages,
                schema=schema,
                schema_name="transaction_category",
                max_tokens=MAX_ANSWER_TOKENS,
            )
        except LLMResponseError as error:
            logger.info(
                "Local AI gave no usable answer for transaction %d: %s", item.transaction_id, error
            )
            return None
        try:
            answer = _Answer.model_validate(reply)
        except ValidationError:
            logger.info(
                "Local AI answer for transaction %d had the wrong shape", item.transaction_id
            )
            return None
        category = by_name.get(answer.category.strip().casefold())
        if category is None:
            logger.info(
                "Local AI picked an unknown category for transaction %d", item.transaction_id
            )
            return None
        return Suggestion(
            category_id=category.id,
            source=CategorySource.LLM,
            confidence=CONFIDENT if answer.confident else UNSURE,
        )


def create_llm_categorizer(environ: Mapping[str, str] | None = None) -> LLMCategorizer | None:
    """Build the LLM tier from the environment, or ``None`` if there is no usable LLM.

    ``None`` when no LLM is configured, the settings are invalid (including an address that
    isn't this computer), or the server doesn't answer a quick health check. The reason is
    logged; the app works without this tier. The check is cheap, so call this per
    categorization run to pick up a server started after the engine.
    """
    try:
        config = load_llm_config(environ)
    except LLMConfigError as error:
        logger.warning("Local AI categorization is off: %s", error)
        return None
    if config is None:
        logger.debug("Local AI categorization is off: no local AI model is set up")
        return None
    client = LLMClient(config)
    if not client.is_available():
        client.close()
        logger.info("Local AI categorization is off: no server is answering at %s", config.base_url)
        return None
    return LLMCategorizer(client)


class _Answer(BaseModel):
    category: StrictStr
    confident: StrictBool


def _answer_schema(categories: Sequence[Category]) -> JsonSchema:
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": [category.name for category in categories]},
            "confident": {"type": "boolean"},
        },
        "required": ["category", "confident"],
        "additionalProperties": False,
    }


def _categories_text(categories: Sequence[Category]) -> str:
    return "\n".join(f"- {category.name} ({category.kind.value})" for category in categories)


def _user_prompt(item: CategorizationInput, categories_text: str) -> str:
    cents = abs(item.amount_cents)
    if item.amount_cents > 0:
        direction = "money in"
    elif item.amount_cents < 0:
        direction = "money out"
    else:
        direction = "no money moved"
    return (
        f"Categories:\n{categories_text}\n\n"
        "Transaction:\n"
        f"Merchant: {item.merchant or 'unknown'}\n"
        f"Bank description: {item.description}\n"
        f"Amount: {cents // 100}.{cents % 100:02d} ({direction})\n"
        f"Date: {item.posted_date.isoformat()}"
    )


def _merchant_key(item: CategorizationInput) -> str:
    """Transactions with the same key get the same answer within a run.

    The cleaned merchant when there is one, otherwise the bank description, ignoring case and
    spacing.
    """
    text = item.merchant if item.merchant is not None else item.description
    return " ".join(text.split()).casefold()
