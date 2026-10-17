"""End-to-end tests that run the engine as a real process, the way the desktop shell does."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import IO

import httpx2 as httpx
import pytest

from monelyth_engine import __version__
from monelyth_engine.__main__ import READY_PREFIX
from monelyth_engine.config import TOKEN_ENV_VAR
from tests.conftest import TOKEN

STARTUP_TIMEOUT_S = 30.0
EXIT_TIMEOUT_S = 15.0


class _LineReader:
    """Reads a pipe on a background thread so tests can wait with a timeout on Windows."""

    def __init__(self, stream: IO[str]) -> None:
        self._lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, args=(stream,), daemon=True).start()

    def _pump(self, stream: IO[str]) -> None:
        for line in stream:
            self._lines.put(line)
        self._lines.put(None)

    def next_line(self, timeout: float) -> str | None:
        return self._lines.get(timeout=timeout)


def _start_engine(
    data_dir: Path, *extra_args: str, token: str | None = TOKEN
) -> subprocess.Popen[str]:
    env = {k: v for k, v in os.environ.items() if k != TOKEN_ENV_VAR}
    if token is not None:
        env[TOKEN_ENV_VAR] = token
    return subprocess.Popen(
        [sys.executable, "-m", "monelyth_engine", "--data-dir", str(data_dir), *extra_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )


def _read_ready_port(process: subprocess.Popen[str]) -> int:
    assert process.stdout is not None
    line = _LineReader(process.stdout).next_line(timeout=STARTUP_TIMEOUT_S)
    assert line is not None, "engine exited before announcing it was ready"
    prefix, _, payload = line.strip().partition(" ")
    assert prefix == READY_PREFIX
    announcement = json.loads(payload)
    assert announcement["version"] == __version__
    port = announcement["port"]
    assert isinstance(port, int)
    return port


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[str], int]]:
    process = _start_engine(tmp_path / "data", "--exit-on-stdin-eof")
    try:
        yield process, _read_ready_port(process)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=EXIT_TIMEOUT_S)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()


def test_engine_announces_port_and_serves_health(
    engine: tuple[subprocess.Popen[str], int], tmp_path: Path
) -> None:
    _, port = engine

    response = httpx.get(
        f"http://127.0.0.1:{port}/health", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
    assert "server" not in response.headers
    assert (tmp_path / "data").is_dir()


def test_engine_rejects_requests_without_token(engine: tuple[subprocess.Popen[str], int]) -> None:
    _, port = engine

    assert httpx.get(f"http://127.0.0.1:{port}/health").status_code == 401


def test_shutdown_command_stops_engine_cleanly(engine: tuple[subprocess.Popen[str], int]) -> None:
    process, _ = engine
    assert process.stdin is not None

    process.stdin.write("shutdown\n")
    process.stdin.flush()

    assert process.wait(timeout=EXIT_TIMEOUT_S) == 0


def test_closing_stdin_stops_engine_cleanly(engine: tuple[subprocess.Popen[str], int]) -> None:
    process, _ = engine
    assert process.stdin is not None

    process.stdin.close()

    assert process.wait(timeout=EXIT_TIMEOUT_S) == 0


def test_missing_token_exits_with_usage_error(tmp_path: Path) -> None:
    process = _start_engine(tmp_path / "data", token=None)
    stdout, stderr = process.communicate(timeout=EXIT_TIMEOUT_S)

    assert process.returncode == 2
    assert stdout == ""
    assert TOKEN_ENV_VAR in stderr


def test_port_in_use_exits_with_error(
    engine: tuple[subprocess.Popen[str], int], tmp_path: Path
) -> None:
    _, busy_port = engine
    process = _start_engine(tmp_path / "other", "--port", str(busy_port))
    stdout, stderr = process.communicate(timeout=EXIT_TIMEOUT_S)

    assert process.returncode == 1
    assert READY_PREFIX not in stdout
    assert "Engine failed to start" in stderr
