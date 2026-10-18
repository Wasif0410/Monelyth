from __future__ import annotations

import pytest

from monelyth_engine.llm.config import (
    DEFAULT_TIMEOUT_SECONDS,
    MODEL_ENV_VAR,
    URL_ENV_VAR,
    LLMConfig,
    load_llm_config,
)
from monelyth_engine.llm.errors import LLMConfigError


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:8080/v1",
        "http://[::1]:8080/v1",
        "http://LOCALHOST:11434/v1",
        "https://localhost/v1",
        "http://127.0.0.1/v1/",
    ],
)
def test_loopback_urls_are_accepted(url: str) -> None:
    assert LLMConfig(base_url=url, model="m").base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://api.openai.com/v1",
        "http://192.168.1.20:11434/v1",
        "http://10.0.0.5/v1",
        "http://0.0.0.0:11434/v1",
        "http://127.0.0.2/v1",
        "http://[::ffff:127.0.0.1]/v1",
        "http://localhost.example.com/v1",
        "http://localhost@example.com/v1",
        "http://user:pass@localhost/v1",
        "http://example.com#@localhost/v1",
        "http://localhost:99999/v1",
        "http://localhost:port/v1",
        "http://localhost/v1?redirect=http://example.com",
        "ftp://localhost/v1",
        "localhost:11434/v1",
        "",
    ],
)
def test_anything_but_this_computer_is_refused(url: str) -> None:
    with pytest.raises(LLMConfigError, match="must be on this computer"):
        LLMConfig(base_url=url, model="m")


def test_blank_model_is_refused() -> None:
    with pytest.raises(LLMConfigError, match="model name is empty"):
        LLMConfig(base_url="http://localhost:11434/v1", model="  ")


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_timeout_must_be_positive_and_finite(timeout: float) -> None:
    with pytest.raises(LLMConfigError, match="timeout"):
        LLMConfig(base_url="http://localhost:11434/v1", model="m", timeout_seconds=timeout)


def test_not_configured_when_neither_variable_is_set() -> None:
    assert load_llm_config({}) is None
    assert load_llm_config({URL_ENV_VAR: " ", MODEL_ENV_VAR: ""}) is None


def test_config_is_read_from_the_environment() -> None:
    config = load_llm_config(
        {URL_ENV_VAR: " http://localhost:11434/v1 ", MODEL_ENV_VAR: "qwen3:4b"}
    )

    assert config == LLMConfig(
        base_url="http://localhost:11434/v1",
        model="qwen3:4b",
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize(
    ("environ", "missing"),
    [
        ({URL_ENV_VAR: "http://localhost:11434/v1"}, MODEL_ENV_VAR),
        ({MODEL_ENV_VAR: "qwen3:4b"}, URL_ENV_VAR),
    ],
)
def test_half_a_configuration_is_an_error(environ: dict[str, str], missing: str) -> None:
    with pytest.raises(LLMConfigError, match=f"{missing} is missing"):
        load_llm_config(environ)


def test_remote_url_in_the_environment_is_refused() -> None:
    with pytest.raises(LLMConfigError, match="must be on this computer"):
        load_llm_config({URL_ENV_VAR: "https://api.openai.com/v1", MODEL_ENV_VAR: "gpt"})
