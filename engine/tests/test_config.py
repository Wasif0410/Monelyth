from __future__ import annotations

from pathlib import Path

import pytest

from monelyth_engine.config import TOKEN_ENV_VAR, ConfigError, load_settings

VALID_TOKEN = "a1B2_c3-D4" * 4


def _load(*args: str, token: str | None = VALID_TOKEN, data_dir: str = "data"):
    env = {} if token is None else {TOKEN_ENV_VAR: token}
    return load_settings(["--data-dir", data_dir, *args], environ=env)


def test_defaults(tmp_path: Path) -> None:
    settings = _load(data_dir=str(tmp_path))

    assert settings.data_dir == tmp_path.resolve()
    assert settings.token == VALID_TOKEN
    assert settings.port == 0
    assert settings.allowed_origins == ()
    assert settings.exit_on_stdin_eof is False
    assert settings.log_level == "info"


def test_all_options() -> None:
    settings = _load(
        "--port",
        "8765",
        "--allowed-origin",
        "http://tauri.localhost",
        "--allowed-origin",
        "http://localhost:1420",
        "--exit-on-stdin-eof",
        "--log-level",
        "debug",
    )

    assert settings.port == 8765
    assert settings.allowed_origins == ("http://tauri.localhost", "http://localhost:1420")
    assert settings.exit_on_stdin_eof is True
    assert settings.log_level == "debug"


def test_relative_data_dir_is_made_absolute() -> None:
    assert _load(data_dir="relative/dir").data_dir.is_absolute()


def test_missing_token_is_rejected() -> None:
    with pytest.raises(ConfigError, match=TOKEN_ENV_VAR):
        _load(token=None)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "short",
        "x" * 31,
        "has space" + "x" * 32,
        "quote'" + "x" * 32,
        "é" * 40,
    ],
)
def test_invalid_token_is_rejected(token: str) -> None:
    with pytest.raises(ConfigError, match="at least 32 characters"):
        _load(token=token)


@pytest.mark.parametrize("port", ["-1", "65536"])
def test_out_of_range_port_is_rejected(port: str) -> None:
    with pytest.raises(ConfigError, match="--port"):
        _load("--port", port)


@pytest.mark.parametrize(
    "origin",
    [
        "tauri.localhost",
        "ftp://tauri.localhost",
        "http://",
        "http://tauri.localhost/",
        "http://tauri.localhost/path",
        "http://tauri.localhost?x=1",
        "http://tauri.localhost#frag",
        "http://user@tauri.localhost",
        "*",
    ],
)
def test_invalid_origin_is_rejected(origin: str) -> None:
    with pytest.raises(ConfigError, match="--allowed-origin"):
        _load("--allowed-origin", origin)


def test_missing_data_dir_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        load_settings([], environ={TOKEN_ENV_VAR: VALID_TOKEN})
    assert excinfo.value.code == 2
