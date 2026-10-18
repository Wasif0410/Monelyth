from __future__ import annotations

import datetime
import json
import logging
import re
from collections.abc import Generator, Mapping

import pytest

from monelyth_engine.categorize.llm_tier import (
    CONFIDENT,
    MAX_ANSWER_TOKENS,
    UNSURE,
    LLMCategorizer,
    create_llm_categorizer,
)
from monelyth_engine.categorize.models import (
    REVIEW_THRESHOLD,
    CategorizationInput,
    Categorizer,
    Suggestion,
)
from monelyth_engine.db.models import Category, CategoryKind, CategorySource
from monelyth_engine.llm.client import LLMClient
from monelyth_engine.llm.config import MODEL_ENV_VAR, URL_ENV_VAR, LLMConfig
from monelyth_engine.llm.errors import LLMUnavailableError
from tests.fake_llm_server import (
    MODEL,
    FakeLLMServer,
    RecordedRequest,
    Reply,
    Responder,
    chat_reply,
    running_fake_llm,
    unused_local_url,
)

SALARY = Category(id=1, name="Salary", kind=CategoryKind.INCOME, parent_id=None)
GROCERIES = Category(id=5, name="Groceries", kind=CategoryKind.EXPENSE, parent_id=None)
SUBSCRIPTIONS = Category(id=12, name="Subscriptions", kind=CategoryKind.EXPENSE, parent_id=None)
TRANSFERS = Category(id=19, name="Transfers", kind=CategoryKind.TRANSFER, parent_id=None)
CATEGORIES = [SALARY, GROCERIES, SUBSCRIPTIONS, TRANSFERS]


@pytest.fixture
def server() -> Generator[FakeLLMServer]:
    with running_fake_llm() as server:
        yield server


@pytest.fixture
def tier(server: FakeLLMServer) -> Generator[LLMCategorizer]:
    client = LLMClient(
        LLMConfig(base_url=server.url, model=MODEL, timeout_seconds=5.0), retry_delay_seconds=0.0
    )
    categorizer = LLMCategorizer(client)
    yield categorizer
    categorizer.close()


def _item(
    transaction_id: int,
    merchant: str | None,
    *,
    description: str | None = None,
    amount_cents: int = -1599,
) -> CategorizationInput:
    return CategorizationInput(
        transaction_id=transaction_id,
        account_id=1,
        posted_date=datetime.date(2026, 10, 1),
        amount_cents=amount_cents,
        description=description or f"{(merchant or 'POS').upper()} 4417 TORONTO ON",
        merchant=merchant,
    )


def _answer(category: str, *, confident: bool = True) -> str:
    return json.dumps({"category": category, "confident": confident})


def _prompt(request: RecordedRequest) -> str:
    content = request.body["messages"][-1]["content"]
    assert isinstance(content, str)
    return content


def _answering(replies: Mapping[str, str | Reply]) -> Responder:
    """Answer each chat request according to the merchant named in its prompt."""

    def respond(request: RecordedRequest) -> Reply:
        match = re.search(r"^Merchant: (.*)$", _prompt(request), re.MULTILINE)
        assert match is not None
        reply = replies[match.group(1)]
        return reply if isinstance(reply, Reply) else chat_reply(reply)

    return respond


def _llm(category: Category, confidence: float) -> Suggestion:
    return Suggestion(category_id=category.id, source=CategorySource.LLM, confidence=confidence)


def test_answers_become_llm_suggestions(server: FakeLLMServer, tier: LLMCategorizer) -> None:
    server.responder = _answering(
        {
            "Netflix": _answer("Subscriptions", confident=True),
            "Corner Store": _answer("Groceries", confident=False),
        }
    )

    results = tier.suggest([_item(1, "Netflix"), _item(2, "Corner Store")], CATEGORIES)

    assert results == [_llm(SUBSCRIPTIONS, CONFIDENT), _llm(GROCERIES, UNSURE)]
    assert [s.needs_review for s in results if s is not None] == [False, True]


def test_confidence_levels_straddle_the_review_threshold() -> None:
    assert UNSURE < REVIEW_THRESHOLD <= CONFIDENT < 1.0


def test_tier_is_a_categorizer(tier: LLMCategorizer) -> None:
    categorizer: Categorizer = tier

    assert categorizer.source is CategorySource.LLM


def test_request_carries_categories_transaction_and_schema(
    server: FakeLLMServer, tier: LLMCategorizer
) -> None:
    server.responder = _answering({"Netflix": _answer("Subscriptions")})

    tier.suggest([_item(1, "Netflix", description="NETFLIX.COM 866-579-7172 CA")], CATEGORIES)

    [request] = server.chat_requests
    system, user = request.body["messages"]
    assert system["role"] == "system"
    assert "exact name" in system["content"]
    assert user["role"] == "user"
    assert user["content"] == (
        "Categories:\n"
        "- Salary (income)\n"
        "- Groceries (expense)\n"
        "- Subscriptions (expense)\n"
        "- Transfers (transfer)\n"
        "\n"
        "Transaction:\n"
        "Merchant: Netflix\n"
        "Bank description: NETFLIX.COM 866-579-7172 CA\n"
        "Amount: 15.99 (money out)\n"
        "Date: 2026-10-01"
    )
    assert request.body["temperature"] == 0.0
    assert request.body["max_tokens"] == MAX_ANSWER_TOKENS
    assert request.body["response_format"]["json_schema"]["schema"] == {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["Salary", "Groceries", "Subscriptions", "Transfers"],
            },
            "confident": {"type": "boolean"},
        },
        "required": ["category", "confident"],
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    ("amount_cents", "expected"),
    [
        (250_000, "Amount: 2500.00 (money in)"),
        (-5, "Amount: 0.05 (money out)"),
        (0, "Amount: 0.00 (no money moved)"),
    ],
)
def test_prompt_states_amount_and_direction(
    server: FakeLLMServer, tier: LLMCategorizer, amount_cents: int, expected: str
) -> None:
    server.responder = _answering({"unknown": _answer("Salary")})

    tier.suggest([_item(1, None, description="PAYROLL", amount_cents=amount_cents)], CATEGORIES)

    [request] = server.chat_requests
    assert "Merchant: unknown\n" in _prompt(request)
    assert expected in _prompt(request)


def test_unknown_category_gives_none_for_that_item_only(
    server: FakeLLMServer, tier: LLMCategorizer
) -> None:
    server.responder = _answering(
        {"Mystery Co": _answer("Pet Supplies"), "Netflix": _answer("Subscriptions")}
    )

    results = tier.suggest([_item(1, "Mystery Co"), _item(2, "Netflix")], CATEGORIES)

    assert results == [None, _llm(SUBSCRIPTIONS, CONFIDENT)]


@pytest.mark.parametrize(
    "bad_reply",
    [
        "Groceries, I think.",
        '{"category": "Groceries"}',
        '{"category": "Groceries", "confident": "yes"}',
        '{"category": 5, "confident": true}',
        '["Groceries", true]',
        "null",
        chat_reply('{"category": "Groc', finish_reason="length"),
        chat_reply(None),
        Reply(status=400, body={"error": {"message": "prompt too long"}}),
    ],
    ids=[
        "prose",
        "missing-field",
        "string-bool",
        "number-category",
        "array",
        "null",
        "cut-off",
        "no-content",
        "request-refused",
    ],
)
def test_unusable_answer_gives_none_and_the_run_continues(
    server: FakeLLMServer, tier: LLMCategorizer, bad_reply: str | Reply
) -> None:
    server.responder = _answering({"Odd Shop": bad_reply, "Netflix": _answer("Subscriptions")})

    results = tier.suggest([_item(1, "Odd Shop"), _item(2, "Netflix")], CATEGORIES)

    assert results == [None, _llm(SUBSCRIPTIONS, CONFIDENT)]


def test_category_name_match_ignores_case_and_spacing(
    server: FakeLLMServer, tier: LLMCategorizer
) -> None:
    # The schema forbids this, but a server that ignores schemas could still send it.
    server.responder = _answering({"Fresh Mart": _answer(" groceries ")})

    assert tier.suggest([_item(1, "Fresh Mart")], CATEGORIES) == [_llm(GROCERIES, CONFIDENT)]


def test_each_merchant_is_asked_once_per_run(server: FakeLLMServer, tier: LLMCategorizer) -> None:
    server.responder = _answering(
        {"Netflix": _answer("Subscriptions"), "Fresh Mart": _answer("Groceries")}
    )
    items = [
        _item(1, "Netflix"),
        _item(2, "Fresh Mart"),
        _item(3, "NETFLIX"),
        _item(4, "Netflix", description="NETFLIX.COM DIFFERENT REF"),
    ]

    results = tier.suggest(items, CATEGORIES)

    assert results == [
        _llm(SUBSCRIPTIONS, CONFIDENT),
        _llm(GROCERIES, CONFIDENT),
        _llm(SUBSCRIPTIONS, CONFIDENT),
        _llm(SUBSCRIPTIONS, CONFIDENT),
    ]
    assert len(server.chat_requests) == 2


def test_unusable_answers_are_cached_too(server: FakeLLMServer, tier: LLMCategorizer) -> None:
    server.responder = _answering({"Odd Shop": "not json"})

    results = tier.suggest([_item(1, "Odd Shop"), _item(2, "Odd Shop")], CATEGORIES)

    assert results == [None, None]
    assert len(server.chat_requests) == 1


def test_without_a_merchant_the_description_is_the_key(
    server: FakeLLMServer, tier: LLMCategorizer
) -> None:
    server.responder = _answering({"unknown": _answer("Salary")})
    items = [
        _item(1, None, description="ACME CORP PAYROLL", amount_cents=250_000),
        _item(2, None, description="acme  corp payroll", amount_cents=250_000),
        _item(3, None, description="ACME CORP BONUS", amount_cents=50_000),
    ]

    results = tier.suggest(items, CATEGORIES)

    assert results == [_llm(SALARY, CONFIDENT)] * 3
    assert len(server.chat_requests) == 2


def test_requests_per_run_are_capped(server: FakeLLMServer) -> None:
    server.responder = _answering(
        {"A": _answer("Groceries"), "B": _answer("Salary"), "C": _answer("Transfers")}
    )
    client = LLMClient(LLMConfig(base_url=server.url, model=MODEL))
    with client:
        tier = LLMCategorizer(client, max_calls_per_run=2)
        items = [_item(1, "A"), _item(2, "B"), _item(3, "C"), _item(4, "A")]

        results = tier.suggest(items, CATEGORIES)

    # "C" is over the cap; the second "A" is already answered, so it costs nothing.
    assert results == [_llm(GROCERIES, CONFIDENT), _llm(SALARY, CONFIDENT), None, results[0]]
    assert len(server.chat_requests) == 2


def test_server_unavailable_from_the_start_raises(
    server: FakeLLMServer, tier: LLMCategorizer
) -> None:
    server.responder = _answering({"Netflix": Reply(status=503, body={})})

    with pytest.raises(LLMUnavailableError):
        tier.suggest([_item(1, "Netflix"), _item(2, "Fresh Mart")], CATEGORIES)
    assert len(server.chat_requests) == 1


def test_server_failing_midway_keeps_earlier_answers(
    server: FakeLLMServer, tier: LLMCategorizer, caplog: pytest.LogCaptureFixture
) -> None:
    down = Reply(status=500, body={})
    server.responder = _answering(
        {"Netflix": _answer("Subscriptions"), "Fresh Mart": down, "Corner Store": down}
    )
    items = [_item(1, "Netflix"), _item(2, "Fresh Mart"), _item(3, "Corner Store")]

    with caplog.at_level(logging.WARNING):
        results = tier.suggest(items, CATEGORIES)

    assert results == [_llm(SUBSCRIPTIONS, CONFIDENT), None, None]
    assert len(server.chat_requests) == 2
    assert "stopped answering after 1 requests" in caplog.text


def test_nothing_to_do_makes_no_requests(server: FakeLLMServer, tier: LLMCategorizer) -> None:
    assert tier.suggest([], CATEGORIES) == []
    assert tier.suggest([_item(1, "Netflix"), _item(2, "Fresh Mart")], []) == [None, None]
    assert server.requests == []


def test_cap_must_be_positive(server: FakeLLMServer) -> None:
    with (
        LLMClient(LLMConfig(base_url=server.url, model=MODEL)) as client,
        pytest.raises(ValueError, match="max_calls_per_run"),
    ):
        LLMCategorizer(client, max_calls_per_run=0)


def test_factory_returns_none_when_no_llm_is_configured() -> None:
    assert create_llm_categorizer({}) is None


@pytest.mark.parametrize(
    "environ",
    [
        {URL_ENV_VAR: "https://api.openai.com/v1", MODEL_ENV_VAR: "gpt"},
        {URL_ENV_VAR: "http://localhost:11434/v1"},
    ],
    ids=["remote-url", "half-configured"],
)
def test_factory_returns_none_for_invalid_settings(
    environ: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert create_llm_categorizer(environ) is None
    assert "Local AI categorization is off" in caplog.text


def test_factory_returns_none_when_the_server_is_down() -> None:
    environ = {URL_ENV_VAR: unused_local_url(), MODEL_ENV_VAR: MODEL}

    assert create_llm_categorizer(environ) is None


def test_factory_returns_a_working_tier_when_the_server_answers(server: FakeLLMServer) -> None:
    server.responder = _with_models(_answering({"Netflix": _answer("Subscriptions")}))

    tier = create_llm_categorizer({URL_ENV_VAR: server.url, MODEL_ENV_VAR: MODEL})

    assert tier is not None
    try:
        assert tier.suggest([_item(1, "Netflix")], CATEGORIES) == [_llm(SUBSCRIPTIONS, CONFIDENT)]
    finally:
        tier.close()
    assert [r.path for r in server.requests] == ["/v1/models", "/v1/chat/completions"]


def _with_models(chat: Responder) -> Responder:
    """Answer the health check's ``GET /models`` too, like a real server."""

    def respond(request: RecordedRequest) -> Reply:
        if request.method == "GET":
            return Reply(body={"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        return chat(request)

    return respond
