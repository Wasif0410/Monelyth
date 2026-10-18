"""The background categorization run: its progress, and starting one on demand."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict

from monelyth_engine.categorize.pipeline import AUTOMATIC, UNCATEGORIZED, UNPROCESSED
from monelyth_engine.categorize.worker import CategorizationWorker, WorkerState, WorkerStatus

router = APIRouter(prefix="/categorization", tags=["categorization"])


def get_worker(request: Request) -> CategorizationWorker:
    # Set by create_app; Starlette types app.state as Any.
    return cast(CategorizationWorker, request.app.state.categorization)


Worker = Annotated[CategorizationWorker, Depends(get_worker)]


STORING_ROUTES: Final = frozenset({("POST", "/imports"), ("POST", "/demo")})
"""The requests that store new transactions. (The import preview, for one, stores nothing.)"""


def _categorize_after_success(request: Request, worker: Worker) -> Iterator[None]:
    # An error raised by the route is re-raised at the yield, so this only queues a run after
    # a request that succeeded, and its database transaction has committed by then.
    yield
    if (request.method, request.url.path) in STORING_ROUTES:
        worker.request(UNPROCESSED)


CATEGORIZE_NEW_TRANSACTIONS: Final = Depends(_categorize_after_success, scope="function")
"""Router dependency for the routers with :data:`STORING_ROUTES` (imports, demo data): queues a
run over the new transactions once such a request succeeds. ``scope="function"`` queues it
before the response is sent, so a client that asks for the status next already sees the run."""


class CategorizationStatusOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: WorkerState
    """``queued``: a run is about to start; ``running``: one is in progress."""
    processed: int
    total: int
    """How many transactions the current (or last) run looks at."""
    last_error: str | None
    """Why the last run failed or skipped a step, written for the user; ``null`` if it didn't."""
    runs_finished: int
    """Counts up each time a run ends: refresh categories when it changes."""

    @classmethod
    def of(cls, worker_status: WorkerStatus) -> CategorizationStatusOut:
        return cls(
            state=worker_status.state,
            processed=worker_status.processed,
            total=worker_status.total,
            last_error=worker_status.last_error,
            runs_finished=worker_status.runs_finished,
        )


class CategorizationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["uncategorized", "all"] = "uncategorized"
    """``uncategorized``: transactions without a category; ``all``: every transaction whose
    category you didn't set, asking every tier again. Categories you set never change."""


@router.get("/status")
def get_categorization_status(worker: Worker) -> CategorizationStatusOut:
    return CategorizationStatusOut.of(worker.status())


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def post_categorization_run(
    body: CategorizationRunRequest, worker: Worker
) -> CategorizationStatusOut:
    """Categorize in the background; poll ``GET /categorization/status`` for progress.

    A request made while a run is going is combined with any other waiting request into one
    next run."""
    worker.request(AUTOMATIC if body.scope == "all" else UNCATEGORIZED)
    return CategorizationStatusOut.of(worker.status())
