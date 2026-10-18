"""A small, typed client for the OpenAI-compatible chat API of a local LLM server.

Ollama (development) and llama.cpp's ``llama-server`` (bundled in the release) both serve
``GET /v1/models`` and ``POST /v1/chat/completions``, so switching runtimes is a change of
:class:`~monelyth_engine.llm.config.LLMConfig`, not of code.

**Structured output.** :meth:`LLMClient.complete_json` sends the standard OpenAI field::

    "response_format": {"type": "json_schema",
                        "json_schema": {"name": ..., "strict": true, "schema": {...}}}

Both runtimes turn that schema into a grammar that constrains generation, so the model cannot
answer with chatty text. ``llama-server`` reads ``response_format.json_schema.schema``; Ollama
(0.5 and later) copies the same value into the ``format`` field of its native API. Ollama's
top-level ``format`` field exists only on that native ``/api/chat`` endpoint: its ``/v1``
endpoint ignores it, so sending it there would silently leave the output unconstrained. One
request shape therefore serves both runtimes and there is nothing to detect.

**Why httpx2 and not the ``openai`` package.** The client needs two endpoints, and the
product's promise is that it sends nothing but what we build. The ``openai`` SDK reads
``OPENAI_API_KEY``, ``OPENAI_ORG_ID``, ``OPENAI_PROJECT_ID`` and ``OPENAI_CUSTOM_HEADERS``
from the environment and attaches them to every request, so a developer's real OpenAI key
would be handed to whatever process listens on the local port. It also adds three packages
to the installer, while httpx2 adds none: it was already locked for the test suite.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Final, Literal, Self

import httpx2 as httpx
from pydantic import BaseModel, ValidationError

from monelyth_engine.llm.config import LLMConfig
from monelyth_engine.llm.errors import LLMResponseError, LLMUnavailableError

logger = logging.getLogger(__name__)

type Role = Literal["system", "user", "assistant"]
type JsonSchema = Mapping[str, object]

HEALTH_CHECK_TIMEOUT_SECONDS: Final = 2.0
""":meth:`LLMClient.is_available` is a quick yes/no, so it waits much less than a request."""

CONNECT_TIMEOUT_SECONDS: Final = 5.0
"""Connecting over loopback is instant unless the computer is very busy."""

DEFAULT_CONNECTION_ATTEMPTS: Final = 3
DEFAULT_RETRY_DELAY_SECONDS: Final = 0.25

# Failures where the request never got a hearing, such as the server restarting or closing an
# idle keep-alive connection: worth a quick retry. Timeouts are not retried; a server that is
# too slow once will be too slow again, and each retry would cost another full timeout.
_CONNECTION_ERRORS: Final = (httpx.NetworkError, httpx.RemoteProtocolError)

# Statuses that mean this particular request was refused (for example, a prompt longer than
# the model's context); other requests may still succeed.
_REQUEST_REFUSED_STATUSES: Final = frozenset({400, 413, 422})


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


class LLMClient:
    """Sends chat requests to the local LLM server described by an :class:`LLMConfig`.

    One instance can serve many requests, and keeps the connection to the server open between
    them. Use it as a context manager, or call :meth:`close` when done.
    """

    def __init__(
        self,
        config: LLMConfig,
        *,
        connection_attempts: int = DEFAULT_CONNECTION_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    ) -> None:
        if connection_attempts < 1:
            raise ValueError(f"connection_attempts must be at least 1, got {connection_attempts}")
        if retry_delay_seconds < 0:
            raise ValueError(f"retry_delay_seconds must not be negative, got {retry_delay_seconds}")
        self._config = config
        self._connection_attempts = connection_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._http = httpx.Client(
            base_url=config.base_url,
            timeout=httpx.Timeout(
                config.timeout_seconds,
                connect=min(CONNECT_TIMEOUT_SECONDS, config.timeout_seconds),
            ),
            # Ignore proxy settings from the environment: a proxy would carry the data off this
            # computer, whatever host the URL names.
            trust_env=False,
            # A redirect could point anywhere; the server must answer at the address configured.
            follow_redirects=False,
        )

    @property
    def config(self) -> LLMConfig:
        return self._config

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def is_available(self) -> bool:
        """Whether the server is up and answering: one quick ``GET /models``. Never raises.

        It doesn't check that the configured model is installed: Ollama and llama-server name
        models differently, and a missing model surfaces as :class:`LLMUnavailableError` on
        the first request anyway.
        """
        try:
            response = self._http.get("models", timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        except httpx.HTTPError:
            return False
        return response.is_success

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Return the model's reply to ``messages`` as plain text.

        Raises:
            LLMUnavailableError: the server is down, too slow, or can't serve the model.
            LLMResponseError: the server refused this request or sent an unusable reply.
        """
        return self._chat(self._chat_body(messages, temperature=temperature, max_tokens=max_tokens))

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        schema: JsonSchema,
        schema_name: str = "answer",
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> object:
        """Return the model's reply, constrained to ``schema``, parsed from JSON.

        The server enforces the schema while generating, but the caller should still validate
        the result: older servers may ignore the constraint, and a reply cut short is not
        valid JSON at all.

        Raises:
            LLMUnavailableError: the server is down, too slow, or can't serve the model.
            LLMResponseError: the server refused this request, or the reply isn't JSON.
        """
        body = self._chat_body(messages, temperature=temperature, max_tokens=max_tokens)
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        }
        text = self._chat(body)
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise LLMResponseError("The local AI model's answer wasn't valid JSON.") from error

    def _chat_body(
        self, messages: Sequence[ChatMessage], *, temperature: float, max_tokens: int | None
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self._config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            # The seam for streaming (Phase 5 chat): a sibling method sends this same body with
            # "stream": true and reads the reply as server-sent events.
            "stream": False,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        return body

    def _chat(self, body: Mapping[str, object]) -> str:
        response = self._post("chat/completions", body)
        try:
            completion = _ChatCompletion.model_validate_json(response.content)
        except ValidationError as error:
            raise LLMResponseError(
                "The local AI server sent a reply in an unexpected format."
            ) from error
        if not completion.choices:
            raise LLMResponseError("The local AI model sent an empty reply.")
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise LLMResponseError("The local AI model's answer was cut off before it finished.")
        if choice.message.content is None:
            raise LLMResponseError("The local AI model sent an empty reply.")
        return choice.message.content

    def _post(self, path: str, body: Mapping[str, object]) -> httpx.Response:
        attempt = 1
        while True:
            try:
                response = self._http.post(path, json=body)
            except httpx.TimeoutException as error:
                raise LLMUnavailableError(
                    f"The local AI model didn't answer within "
                    f"{self._config.timeout_seconds:g} seconds."
                ) from error
            except _CONNECTION_ERRORS as error:
                if attempt >= self._connection_attempts:
                    raise LLMUnavailableError(
                        f"Couldn't reach the local AI server at {self._config.base_url}. "
                        "Is it running?"
                    ) from error
                logger.debug("LLM connection failed (attempt %d), retrying: %s", attempt, error)
                time.sleep(self._retry_delay_seconds * attempt)
                attempt += 1
                continue
            except httpx.HTTPError as error:
                raise LLMUnavailableError(
                    f"Couldn't talk to the local AI server at {self._config.base_url}."
                ) from error
            return self._check_status(response)

    def _check_status(self, response: httpx.Response) -> httpx.Response:
        if response.is_success:
            return response
        status = response.status_code
        server = f"The local AI server at {self._config.base_url}"
        if status in _REQUEST_REFUSED_STATUSES:
            raise LLMResponseError(f"{server} refused the request (HTTP {status}).")
        if status == 404:
            raise LLMUnavailableError(
                f"{server} answered 'not found'. Check that the model {self._config.model!r} "
                "is installed and that the address ends in /v1."
            )
        if status == 503:
            raise LLMUnavailableError(f"{server} isn't ready yet; it may still be loading.")
        raise LLMUnavailableError(f"{server} returned an error (HTTP {status}).")


class _ResponseMessage(BaseModel):
    content: str | None = None


class _Choice(BaseModel):
    message: _ResponseMessage
    finish_reason: str | None = None


class _ChatCompletion(BaseModel):
    """The part of an OpenAI-style chat completion this client reads; other fields are ignored."""

    choices: list[_Choice]
