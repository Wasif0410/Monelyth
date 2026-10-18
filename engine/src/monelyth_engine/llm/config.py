"""Where the local LLM server is and which model to ask.

For now both values come from environment variables, for example (Ollama in development)::

    MONELYTH_LLM_URL=http://localhost:11434/v1
    MONELYTH_LLM_MODEL=qwen3:4b

or (llama.cpp, which serves whichever model it was started with and ignores the name)::

    MONELYTH_LLM_URL=http://127.0.0.1:8080/v1
    MONELYTH_LLM_MODEL=default

Phase 6 bundles ``llama-server`` and builds an :class:`LLMConfig` for it directly.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from monelyth_engine.llm.errors import LLMConfigError

URL_ENV_VAR: Final = "MONELYTH_LLM_URL"
MODEL_ENV_VAR: Final = "MONELYTH_LLM_MODEL"

DEFAULT_TIMEOUT_SECONDS: Final = 60.0
"""How long one request may take. Generous because the first request after the server starts
also loads the model from disk, which can take tens of seconds on a laptop."""

LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})
"""The only hosts the client will talk to. This is the product's privacy promise: transaction
data is never sent to another machine, so any other address is refused outright."""

_SCHEMES: Final = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class LLMConfig:
    base_url: str
    """The OpenAI-compatible API root, including the ``/v1`` path."""
    model: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _validate_base_url(self.base_url)
        if not self.model.strip():
            raise LLMConfigError("The local AI model name is empty.")
        if not (math.isfinite(self.timeout_seconds) and self.timeout_seconds > 0):
            raise LLMConfigError(
                f"The local AI timeout must be a positive number of seconds, "
                f"got {self.timeout_seconds}."
            )


def load_llm_config(environ: Mapping[str, str] | None = None) -> LLMConfig | None:
    """Read the LLM settings from ``environ`` (defaults to ``os.environ``).

    Returns ``None`` when neither variable is set, meaning the user hasn't set up a local LLM.

    Raises:
        LLMConfigError: if only one of the variables is set, or a value is invalid
            (including a server address that isn't this computer).
    """
    env = os.environ if environ is None else environ
    url = env.get(URL_ENV_VAR, "").strip()
    model = env.get(MODEL_ENV_VAR, "").strip()
    if not url and not model:
        return None
    if not url or not model:
        missing = URL_ENV_VAR if not url else MODEL_ENV_VAR
        raise LLMConfigError(
            f"To use a local AI model, set both {URL_ENV_VAR} and {MODEL_ENV_VAR}; "
            f"{missing} is missing."
        )
    return LLMConfig(base_url=url, model=model)


def _validate_base_url(url: str) -> None:
    """Accept only ``http(s)://<loopback host>[:port][/path]``, nothing that could leave the PC."""
    refusal = (
        f"The local AI server address must be on this computer "
        f"(127.0.0.1, localhost or [::1]), like http://localhost:11434/v1; got {url!r}."
    )
    parts = urlsplit(url)
    try:
        # Reading .port validates it: a non-numeric or out-of-range port raises ValueError.
        _ = parts.port
    except ValueError as error:
        raise LLMConfigError(refusal) from error
    is_loopback_url = (
        parts.scheme in _SCHEMES
        and parts.hostname in LOOPBACK_HOSTS
        # Credentials in the URL ("http://user@host") are a classic way to disguise the host.
        and "@" not in parts.netloc
        and not parts.query
        and not parts.fragment
    )
    if not is_loopback_url:
        raise LLMConfigError(refusal)
