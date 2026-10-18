"""The background worker, synchronized with events rather than sleeps."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from monelyth_engine.categorize import worker as worker_module
from monelyth_engine.categorize.models import CategorizationInput, Suggestion
from monelyth_engine.categorize.pipeline import (
    AUTOMATIC,
    BATCH_SIZE,
    UNCATEGORIZED,
    UNPROCESSED,
    RunResult,
    RunScope,
)
from monelyth_engine.categorize.tiers import PipelineExtensions
from monelyth_engine.categorize.worker import (
    RUN_FAILED_MESSAGE,
    CategorizationWorker,
    WorkerState,
    WorkerStatus,
)
from monelyth_engine.database import Database
from monelyth_engine.db.models import Category, CategorySource
from tests.db.conftest import ImportStatement, raw

TIMEOUT = 10.0
"""Generous upper bound for waits that normally finish in milliseconds."""


class GatedTier:
    """A tier that tells the test when it is asked, then waits for the test to let it answer."""

    def __init__(self, *, on_call: Callable[[int], None] | None = None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[list[int]] = []
        self._on_call = on_call

    @property
    def source(self) -> CategorySource:
        return CategorySource.CLASSIFIER

    def suggest(
        self, items: Sequence[CategorizationInput], categories: Sequence[Category]
    ) -> list[Suggestion | None]:
        self.calls.append([entry.transaction_id for entry in items])
        if self._on_call is not None:
            self._on_call(len(self.calls))
        self.entered.set()
        if not self.release.wait(TIMEOUT):
            raise TimeoutError("the test never released the tier")
        return [None] * len(items)


@pytest.fixture
def database(db_path: Path, db: sqlite3.Connection) -> Database:
    """The same file the ``db`` fixture opened, as the engine sees it."""
    return Database(db_path.parent)


@pytest.fixture
def make_worker(database: Database) -> Iterator[Callable[..., CategorizationWorker]]:
    workers: list[CategorizationWorker] = []

    def make(*tiers: GatedTier) -> CategorizationWorker:
        extensions = PipelineExtensions(
            optional_tiers=(lambda _conn: list(tiers)) if tiers else None
        )
        worker = CategorizationWorker(database, extensions)
        workers.append(worker)
        return worker

    yield make
    for worker in workers:
        worker.stop(TIMEOUT)


@pytest.fixture
def mystery(import_statement: ImportStatement) -> None:
    """One transaction no built-in tier can answer."""
    import_statement([raw(1, -999, "MYSTERY SHOP 123")], file_label="mystery")


def _wait_idle(worker: CategorizationWorker) -> WorkerStatus:
    assert worker.wait_until_idle(TIMEOUT)
    return worker.status()


def test_runs_in_the_background_and_reports_progress(
    make_worker: Callable[..., CategorizationWorker], mystery: None
) -> None:
    tier = GatedTier()
    worker = make_worker(tier)
    worker.start()

    worker.request(UNPROCESSED)
    assert tier.entered.wait(TIMEOUT)
    assert worker.status() == WorkerStatus(WorkerState.RUNNING, 0, 1, None, 0)

    tier.release.set()
    assert _wait_idle(worker) == WorkerStatus(WorkerState.IDLE, 1, 1, None, 1)


def test_requests_made_during_a_run_become_one_next_run(
    make_worker: Callable[..., CategorizationWorker], mystery: None
) -> None:
    tier = GatedTier()
    worker = make_worker(tier)
    worker.start()
    worker.request(UNPROCESSED)
    assert tier.entered.wait(TIMEOUT)

    worker.request(UNCATEGORIZED)
    worker.request(RunScope(transaction_ids=frozenset({1})))
    worker.request(UNCATEGORIZED)
    assert worker.status().state is WorkerState.RUNNING

    tier.release.set()
    status = _wait_idle(worker)

    # The first run, then one run for the three requests.
    assert status.runs_finished == 2
    assert len(tier.calls) == 2


def test_a_request_before_start_waits_for_it(
    make_worker: Callable[..., CategorizationWorker], mystery: None
) -> None:
    worker = make_worker()

    worker.request(UNPROCESSED)
    assert worker.status().state is WorkerState.QUEUED

    worker.start()
    assert _wait_idle(worker).runs_finished == 1


def test_a_failed_run_is_reported_and_the_next_one_clears_it(
    make_worker: Callable[..., CategorizationWorker], monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = make_worker()
    real_run = worker_module.run_categorization

    def broken(*args: object, **kwargs: object) -> RunResult:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(worker_module, "run_categorization", broken)
    worker.start()
    worker.request(AUTOMATIC)
    assert _wait_idle(worker).last_error == RUN_FAILED_MESSAGE

    monkeypatch.setattr(worker_module, "run_categorization", real_run)
    worker.request(AUTOMATIC)
    status = _wait_idle(worker)
    assert status.last_error is None
    assert status.runs_finished == 2


def test_a_skipped_tier_is_reported_without_failing_the_run(
    make_worker: Callable[..., CategorizationWorker], mystery: None
) -> None:
    def fail(_call: int) -> None:
        raise RuntimeError("model file missing")

    worker = make_worker(GatedTier(on_call=fail))
    worker.start()
    worker.request(UNPROCESSED)

    status = _wait_idle(worker)
    assert status.last_error is not None
    assert "skipped: The classifier" in status.last_error
    assert (status.processed, status.total) == (1, 1)


def test_stopping_ends_the_run_after_the_current_batch(
    make_worker: Callable[..., CategorizationWorker],
    import_statement: ImportStatement,
    db: sqlite3.Connection,
) -> None:
    import_statement(
        [raw(1, -100, f"MYSTERY {n}") for n in range(BATCH_SIZE * 2)], file_label="many"
    )
    workers: list[CategorizationWorker] = []

    def stop_during_first_batch(call: int) -> None:
        if call == 1:
            workers[0].request_stop()

    tier = GatedTier(on_call=stop_during_first_batch)
    tier.release.set()
    worker = make_worker(tier)
    workers.append(worker)
    worker.start()
    worker.request(UNPROCESSED)
    assert tier.entered.wait(TIMEOUT)

    worker.stop(TIMEOUT)

    assert len(tier.calls) == 1
    flagged = db.execute("SELECT COUNT(*) FROM transactions WHERE needs_review = 1").fetchone()
    assert flagged[0] == BATCH_SIZE
    # Requests after stopping are ignored.
    worker.request(AUTOMATIC)
    assert worker.status().state is WorkerState.IDLE


def test_starting_twice_is_a_bug(make_worker: Callable[..., CategorizationWorker]) -> None:
    worker = make_worker()
    worker.start()

    with pytest.raises(RuntimeError, match="already started"):
        worker.start()


def test_stop_without_start_returns(make_worker: Callable[..., CategorizationWorker]) -> None:
    worker = make_worker()

    worker.stop(TIMEOUT)
    assert worker.wait_until_idle(TIMEOUT)
