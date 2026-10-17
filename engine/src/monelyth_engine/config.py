"""Engine settings, parsed from the command line and environment."""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

HOST: Final = "127.0.0.1"
"""The engine only ever listens on loopback, so it is unreachable from the network."""

TOKEN_ENV_VAR: Final = "MONELYTH_TOKEN"  # noqa: S105 -- the variable name, not a secret
MIN_TOKEN_LENGTH: Final = 32
LOG_LEVELS: Final = ("debug", "info", "warning", "error")

_TOKEN_PATTERN: Final = re.compile(rf"[A-Za-z0-9_-]{{{MIN_TOKEN_LENGTH},}}")
_ORIGIN_SCHEMES: Final = frozenset({"http", "https", "tauri"})


class ConfigError(ValueError):
    """Raised when the engine is started with invalid settings."""


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    token: str
    port: int
    allowed_origins: tuple[str, ...]
    exit_on_stdin_eof: bool
    log_level: str


def load_settings(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Build settings from ``argv`` (defaults to ``sys.argv[1:]``) and ``environ``.

    Raises:
        ConfigError: if the token or any option value is invalid.
        SystemExit: if the arguments cannot be parsed (argparse prints usage).
    """
    args = _build_parser().parse_args(argv)
    env = os.environ if environ is None else environ

    port: int = args.port
    if not 0 <= port <= 65535:
        raise ConfigError(f"--port must be between 0 and 65535, got {port}")

    origins: list[str] = args.allowed_origin
    return Settings(
        data_dir=Path(args.data_dir).expanduser().resolve(),
        token=_validate_token(env.get(TOKEN_ENV_VAR)),
        port=port,
        allowed_origins=tuple(_validate_origin(origin) for origin in origins),
        exit_on_stdin_eof=args.exit_on_stdin_eof,
        log_level=args.log_level,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monelyth-engine",
        description="Local engine for the Monelyth desktop app.",
        epilog=f"The API token is read from the {TOKEN_ENV_VAR} environment variable.",
    )
    parser.add_argument(
        "--data-dir", required=True, help="folder for the database and other user data"
    )
    parser.add_argument(
        "--port", type=int, default=0, help="port to listen on (0 = pick a free port)"
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        metavar="URL",
        help="origin allowed to call the API from a webview; repeat for several",
    )
    parser.add_argument(
        "--exit-on-stdin-eof",
        action="store_true",
        help="exit when stdin closes or receives a 'shutdown' line",
    )
    parser.add_argument("--log-level", choices=LOG_LEVELS, default="info")
    return parser


def _validate_token(token: str | None) -> str:
    if token is None:
        raise ConfigError(f"the {TOKEN_ENV_VAR} environment variable must be set")
    if not _TOKEN_PATTERN.fullmatch(token):
        raise ConfigError(
            f"{TOKEN_ENV_VAR} must be at least {MIN_TOKEN_LENGTH} characters "
            "of A-Z, a-z, 0-9, '_' or '-'"
        )
    return token


def _validate_origin(origin: str) -> str:
    """Accept only a bare origin such as ``http://tauri.localhost`` (no path, query or slash)."""
    parts = urlsplit(origin)
    is_bare_origin = (
        parts.scheme in _ORIGIN_SCHEMES
        and bool(parts.netloc)
        and not parts.path
        and not parts.query
        and not parts.fragment
        and "@" not in parts.netloc
    )
    if not is_bare_origin:
        raise ConfigError(f"--allowed-origin must look like 'http://host[:port]', got {origin!r}")
    return origin
