"""The background worker that categorizes transactions without holding up requests.

One thread does every run, so runs never overlap. Requests that arrive while it is busy are
merged into a single next run (:meth:`~monelyth_engine.categorize.pipeline.RunScope.merge`),
so ten quick rule edits cost one extra run, not ten.

The thread opens its own database connection for each run, like a request does, so it never
shares a connection with request handlers. Its writes are guarded in SQL (see
:mod:`monelyth_engine.db.categorization`), so a user's edit made during a run always stands.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fastapi import FastAPI

from monelyth_engine.categorize.pipeline import (
    UNPROCESSED,
    RunResult,
    RunScope,
    run_categorization,
)
from monelyth_engine.categorize.tiers import PipelineExtensions
from monelyth_engine.database import Database

STOP_TIMEOUT_SECONDS: Final = 10.0
"""How long shutdown waits for the current batch. The thread is a daemon, so if a tier hangs
the process still exits; SQLite rolls back the unfinished batch on the next start."""

RUN_FAILED_MESSAGE: Final = (
    "Automatic categorization stopped because of an unexpected error. "
    "The details are in the app's log file."
)

logger = logging.getLogger(__name__)


class WorkerState(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    """A run is waiting to start."""
    RUNNING = "running"


@dataclass(frozen=True, slots=True)
class WorkerStatus:
    state: WorkerState
    processed: int
    """Of the current run (or the last one, when idle)."""
    total: int
    last_error: str | None
    """Why the last finished run failed or skipped part of its work; ``None`` if it didn't."""
    runs_finished: int
    """Counts up each time a run ends, so a client can tell that categories may have changed."""


class CategorizationWorker:
    """Runs :func:`~monelyth_engine.categorize.pipeline.run_categorization` on its own thread.

    Call :meth:`start` once, :meth:`request` whenever transactions may need categorizing, and
    :meth:`stop` at shutdown. :meth:`request` works before :meth:`start` too: the run waits
    until the worker starts. Every method is safe to call from any thread.
    """

    def __init__(self, database: Database, extensions: PipelineExtensions) -> None:
        self._database = database
        self._extensions = extensions
        self._changed = threading.Condition()
        self._pending: RunScope | None = None
        self._running = False
        self._stopping = False
        self._thread: threading.Thread | None = None
        self._processed = 0
        self._total = 0
        self._last_error: str | None = None
        self._runs_finished = 0

    def start(self) -> None:
        """Start the thread.

        Raises:
            RuntimeError: if the worker was started before.
        """
        with self._changed:
            if self._thread is not None:
                raise RuntimeError("The categorization worker was already started")
            self._thread = threading.Thread(
                target=self._work, name="categorization-worker", daemon=True
            )
            self._thread.start()

    def request(self, scope: RunScope) -> None:
        """Ask for a run over ``scope``, merged with any run already waiting."""
        with self._changed:
            if self._stopping:
                return
            self._pending = scope if self._pending is None else self._pending.merge(scope)
            self._changed.notify_all()

    def status(self) -> WorkerStatus:
        with self._changed:
            if self._running:
                state = WorkerState.RUNNING
            elif self._pending is not None:
                state = WorkerState.QUEUED
            else:
                state = WorkerState.IDLE
            return WorkerStatus(
                state=state,
                processed=self._processed,
                total=self._total,
                last_error=self._last_error,
                runs_finished=self._runs_finished,
            )

    def wait_until_idle(self, timeout: float) -> bool:
        """Block until no run is going or waiting; returns ``False`` if ``timeout`` (seconds)
        passed first. Lets tests (and shutdown) synchronize without sleeping."""
        with self._changed:
            return self._changed.wait_for(
                lambda: not self._running and self._pending is None, timeout
            )

    def request_stop(self) -> None:
        """Drop any waiting run and ask the current one to end after its batch. Returns at once;
        later requests are ignored."""
        with self._changed:
            self._stopping = True
            self._pending = None
            self._changed.notify_all()

    def stop(self, timeout: float = STOP_TIMEOUT_SECONDS) -> None:
        """:meth:`request_stop`, then wait up to ``timeout`` seconds for the thread to end."""
        self.request_stop()
        with self._changed:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                logger.warning("Categorization did not stop within %.0f seconds", timeout)

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncGenerator[None]:
        """FastAPI lifespan: start with the engine, catch up on anything never categorized
        (e.g. imported by an older version, or left when the app closed mid-run), and stop
        with the engine."""
        self.start()
        self.request(UNPROCESSED)
        try:
            yield
        finally:
            # On a thread, so the event loop isn't blocked while the last batch finishes.
            await asyncio.to_thread(self.stop)

    def _work(self) -> None:
        while True:
            with self._changed:
                self._changed.wait_for(lambda: self._stopping or self._pending is not None)
                if self._stopping:
                    return
                scope = self._pending
                self._pending = None
                self._running = True
                self._processed = 0
                self._total = 0
            if scope is None:  # pragma: no cover - wait_for guarantees a pending run
                continue
            error = self._run(scope)
            with self._changed:
                self._running = False
                self._last_error = error
                self._runs_finished += 1
                self._changed.notify_all()

    def _run(self, scope: RunScope) -> str | None:
        """One run; returns the problem to report, if any. Never raises."""
        try:
            with self._database.connection() as conn:
                result = run_categorization(
                    conn,
                    scope,
                    extensions=self._extensions,
                    on_progress=self._progress,
                    should_stop=self._should_stop,
                )
        except Exception:
            logger.exception("Categorization run failed")
            return RUN_FAILED_MESSAGE
        return _problem_message(result)

    def _progress(self, processed: int, total: int) -> None:
        with self._changed:
            self._processed = processed
            self._total = total

    def _should_stop(self) -> bool:
        with self._changed:
            return self._stopping


def _problem_message(result: RunResult) -> str | None:
    if not result.problems:
        return None
    names = ", ".join(result.problems)
    return (
        f"Some categorization steps failed and were skipped: {names}. Everything else was "
        "categorized; the details are in the app's log file."
    )
