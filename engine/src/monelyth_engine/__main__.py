"""Entry point: ``python -m monelyth_engine`` or the ``monelyth-engine`` executable.

Startup contract with the desktop shell:

1. The shell starts the engine with ``MONELYTH_TOKEN`` in the environment.
2. The engine binds a loopback socket and prints exactly one line to stdout::

       MONELYTH_READY {"port": 51234, "version": "0.1.0"}

   Nothing else is ever written to stdout; logs go to stderr.
3. With ``--exit-on-stdin-eof`` the engine shuts down gracefully when the shell writes
   ``shutdown`` to its stdin, or when stdin closes because the shell exited or crashed.
"""

from __future__ import annotations

import json
import logging
import socket
import sqlite3
import sys
import threading
from collections.abc import Sequence
from typing import BinaryIO, Final

import uvicorn

from monelyth_engine import __version__
from monelyth_engine.app import create_app
from monelyth_engine.config import HOST, ConfigError, Settings, load_settings
from monelyth_engine.db.errors import SchemaVersionError

READY_PREFIX: Final = "MONELYTH_READY"
SHUTDOWN_COMMAND: Final = b"shutdown"
_BACKLOG: Final = 128

logger = logging.getLogger("monelyth_engine")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        settings = load_settings(argv)
    except ConfigError as error:
        print(f"monelyth-engine: error: {error}", file=sys.stderr)
        return 2

    _configure_logging(settings.log_level)
    try:
        return _serve(settings)
    except SchemaVersionError as error:
        logger.error("Engine failed to start: %s", error)
        return 1
    except (OSError, sqlite3.Error):
        logger.exception("Engine failed to start")
        return 1


def _serve(settings: Settings) -> int:
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            loop="asyncio",
            http="h11",
            ws="none",
            lifespan="on",
            log_config=None,
            log_level=settings.log_level,
            access_log=False,
            server_header=False,
        )
    )

    if settings.exit_on_stdin_eof:
        if sys.stdin is None:  # pyright: ignore[reportUnnecessaryComparison]
            logger.error("--exit-on-stdin-eof was given but the process has no stdin")
            return 2
        _watch_stdin_for_shutdown(server, sys.stdin.buffer)

    sock = _bind_loopback_socket(settings.port)
    port: int = sock.getsockname()[1]
    # Announcing before uvicorn starts is safe: the socket is already listening, so the OS
    # queues any connection that arrives first and uvicorn serves it once it is up.
    print(f"{READY_PREFIX} {json.dumps({'port': port, 'version': __version__})}", flush=True)
    logger.info("Monelyth engine %s listening on %s:%d", __version__, HOST, port)

    server.run(sockets=[sock])
    if not server.started:
        logger.error("Engine stopped before it finished starting")
        return 1
    logger.info("Monelyth engine stopped")
    return 0


def _bind_loopback_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            # Stop any other process from binding the same port and intercepting requests.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((HOST, port))
        sock.listen(_BACKLOG)
    except OSError:
        sock.close()
        raise
    return sock


def _watch_stdin_for_shutdown(server: uvicorn.Server, stream: BinaryIO) -> threading.Thread:
    """Ask ``server`` to stop on a ``shutdown`` line or when ``stream`` reaches EOF."""

    def watch() -> None:
        reason = "stdin closed"
        try:
            for line in stream:
                if line.strip() == SHUTDOWN_COMMAND:
                    reason = "shutdown requested"
                    break
        except (OSError, ValueError):
            reason = "stdin became unreadable"
        logger.info("Stopping engine: %s", reason)
        server.should_exit = True

    thread = threading.Thread(target=watch, name="stdin-shutdown-watcher", daemon=True)
    thread.start()
    return thread


def _configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


if __name__ == "__main__":
    raise SystemExit(main())
