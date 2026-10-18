from __future__ import annotations

import time
from collections.abc import Callable, Generator
from typing import Any

import pytest

from monelyth_engine.llm.client import ChatMessage, LLMClient
from monelyth_engine.llm.config import LLMConfig
from monelyth_engine.llm.errors import LLMResponseError, LLMUnavailableError
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

MESSAGES = [
    ChatMessage(role="system", content="Answer briefly."),
    ChatMessage(role="user", content="Say hi."),
]
SCHEMA = {
    "type": "object",
    "properties": {"greeting": {"type": "string", "enum": ["hi", "hello"]}},
    "required": ["greeting"],
    "additionalProperties": False,
}


@pytest.fixture
def server() -> Generator[FakeLLMServer]:
    with running_fake_llm() as server:
        yield server


def _client(url: str, *, timeout: float = 5.0, attempts: int = 3) -> LLMClient:
    return LLMClient(
        LLMConfig(base_url=url, model=MODEL, timeout_seconds=timeout),
        connection_attempts=attempts,
        retry_delay_seconds=0.0,
    )


def _always(reply: Reply) -> Responder:
    def respond(_request: RecordedRequest) -> Reply:
        return reply

    return respond


def test_complete_returns_the_reply_text(server: FakeLLMServer) -> None:
    server.responder = _always(chat_reply("hi there"))

    with _client(server.url) as client:
        assert client.complete(MESSAGES, max_tokens=20) == "hi there"

    [request] = server.chat_requests
    assert request.method == "POST"
    assert request.body == {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": "Say hi."},
        ],
        "temperature": 0.0,
        "stream": False,
        "max_tokens": 20,
    }


def test_complete_json_sends_the_schema_and_parses_the_reply(server: FakeLLMServer) -> None:
    server.responder = _always(chat_reply('{"greeting": "hello"}'))

    with _client(server.url) as client:
        answer = client.complete_json(MESSAGES, schema=SCHEMA, schema_name="greeting")

    assert answer == {"greeting": "hello"}
    [request] = server.chat_requests
    assert request.body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "greeting", "strict": True, "schema": SCHEMA},
    }


def _schema_as_llama_server_reads_it(body: dict[str, Any]) -> object:
    """llama.cpp server: ``response_format`` of type ``json_object`` (schema inline) or
    ``json_schema`` (schema under ``json_schema.schema``); any other type is rejected."""
    response_format = body.get("response_format", {})
    kind = response_format.get("type", "")
    if kind == "json_object":
        return response_format.get("schema", {})
    if kind == "json_schema":
        return response_format.get("json_schema", {}).get("schema", {})
    assert kind in ("", "text"), f"llama-server rejects response_format type {kind!r}"
    return None


def _schema_as_ollama_reads_it(body: dict[str, Any]) -> object:
    """Ollama's /v1 layer: only ``response_format`` sets the native ``format``; a top-level
    ``format`` key is not part of its OpenAI request type and is dropped."""
    response_format = body.get("response_format")
    if response_format is None:
        return None
    kind = response_format.get("type", "").strip().lower()
    if kind == "json_object":
        return "json"
    if kind == "json_schema" and response_format.get("json_schema") is not None:
        return response_format["json_schema"]["schema"]
    return None


@pytest.mark.parametrize(
    "read_schema",
    [_schema_as_llama_server_reads_it, _schema_as_ollama_reads_it],
    ids=["llama-server", "ollama"],
)
def test_one_request_shape_constrains_both_runtimes(
    server: FakeLLMServer, read_schema: Callable[[dict[str, Any]], object]
) -> None:
    server.responder = _always(chat_reply('{"greeting": "hi"}'))

    with _client(server.url) as client:
        client.complete_json(MESSAGES, schema=SCHEMA)

    [request] = server.chat_requests
    assert read_schema(request.body) == SCHEMA
    assert "format" not in request.body


def test_reply_that_is_not_json_is_a_response_error(server: FakeLLMServer) -> None:
    server.responder = _always(chat_reply("Sure! The greeting is hi."))

    with _client(server.url) as client, pytest.raises(LLMResponseError, match="valid JSON"):
        client.complete_json(MESSAGES, schema=SCHEMA)


def test_cut_off_reply_is_a_response_error(server: FakeLLMServer) -> None:
    server.responder = _always(chat_reply('{"greet', finish_reason="length"))

    with _client(server.url) as client, pytest.raises(LLMResponseError, match="cut off"):
        client.complete_json(MESSAGES, schema=SCHEMA)


@pytest.mark.parametrize(
    "reply",
    [
        Reply(body=b"<html>not an API</html>"),
        Reply(body={"unexpected": True}),
        Reply(body={"choices": []}),
        chat_reply(None),
    ],
    ids=["not-json", "no-choices-field", "empty-choices", "null-content"],
)
def test_malformed_completion_is_a_response_error(server: FakeLLMServer, reply: Reply) -> None:
    server.responder = _always(reply)

    with _client(server.url) as client, pytest.raises(LLMResponseError):
        client.complete(MESSAGES)


@pytest.mark.parametrize("status", [400, 413, 422])
def test_refused_request_is_a_response_error(server: FakeLLMServer, status: int) -> None:
    server.responder = _always(Reply(status=status, body={"error": {"message": "too long"}}))

    with _client(server.url) as client, pytest.raises(LLMResponseError, match=f"HTTP {status}"):
        client.complete(MESSAGES)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (404, "Check that the model 'test-model' is installed"),
        (503, "may still be loading"),
        (500, "HTTP 500"),
        (401, "HTTP 401"),
        (302, "HTTP 302"),
    ],
)
def test_server_errors_mean_unavailable(server: FakeLLMServer, status: int, message: str) -> None:
    server.responder = _always(Reply(status=status, body={"error": {"message": "nope"}}))

    with _client(server.url) as client, pytest.raises(LLMUnavailableError, match=message):
        client.complete(MESSAGES)
    assert len(server.chat_requests) == 1


def test_timeout_is_unavailable_and_not_retried(server: FakeLLMServer) -> None:
    server.responder = _always(Reply(delay_seconds=5.0, body={}))

    started = time.perf_counter()
    with (
        _client(server.url, timeout=0.3) as client,
        pytest.raises(LLMUnavailableError, match=r"didn't answer within 0\.3 seconds"),
    ):
        client.complete(MESSAGES)

    assert time.perf_counter() - started < 3.0
    assert len(server.chat_requests) == 1


def test_dropped_connections_are_retried(server: FakeLLMServer) -> None:
    def respond(request: RecordedRequest) -> Reply:
        if len(server.chat_requests) < 3:
            return Reply(drop_connection=True)
        return chat_reply("hi")

    server.responder = respond

    with _client(server.url, attempts=3) as client:
        assert client.complete(MESSAGES) == "hi"
    assert len(server.chat_requests) == 3


def test_retries_are_bounded(server: FakeLLMServer) -> None:
    server.responder = _always(Reply(drop_connection=True))

    with (
        _client(server.url, attempts=2) as client,
        pytest.raises(LLMUnavailableError, match="Is it running"),
    ):
        client.complete(MESSAGES)
    assert len(server.chat_requests) == 2


def test_is_available_when_the_server_lists_models(server: FakeLLMServer) -> None:
    with _client(server.url) as client:
        assert client.is_available() is True

    assert [(r.method, r.path) for r in server.requests] == [("GET", "/v1/models")]


def test_is_not_available_when_the_server_errors(server: FakeLLMServer) -> None:
    server.responder = _always(Reply(status=500, body={}))

    with _client(server.url) as client:
        assert client.is_available() is False


def test_is_not_available_when_nothing_is_listening() -> None:
    with _client(unused_local_url()) as client:
        assert client.is_available() is False


def test_proxy_settings_in_the_environment_are_ignored(
    server: FakeLLMServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the client honoured these, the request would go to the (dead) proxy and fail.
    proxy = unused_local_url().removesuffix("/v1")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
        monkeypatch.setenv(name, proxy)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    server.responder = _always(chat_reply("hi"))

    with _client(server.url, attempts=1) as client:
        assert client.complete(MESSAGES) == "hi"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"connection_attempts": 0}, "connection_attempts"),
        ({"retry_delay_seconds": -1.0}, "retry_delay_seconds"),
    ],
)
def test_invalid_retry_settings_are_rejected(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        LLMClient(LLMConfig(base_url="http://localhost:11434/v1", model=MODEL), **kwargs)
