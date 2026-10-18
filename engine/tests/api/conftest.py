from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from monelyth_engine.app import create_app
from monelyth_engine.categorize.worker import CategorizationWorker
from monelyth_engine.config import Settings
from tests.conftest import TOKEN

SAMPLE_DATA: Final = Path(__file__).resolve().parents[3] / "sample-data"


@pytest.fixture
def api(make_settings: Callable[..., Settings]) -> TestClient:
    """An authorized client for a fresh, empty database.

    The engine's lifespan doesn't run, so neither does background categorization: requests to
    categorize stay queued and nothing is categorized behind the test's back."""
    return TestClient(
        create_app(make_settings()),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


def create_account(
    api: TestClient, *, name: str = "Main Checking", currency: str = "CAD", **extra: Any
) -> dict[str, Any]:
    response = api.post(
        "/accounts", json={"name": name, "type": "checking", "currency": currency, **extra}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
def running_api(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    """Like ``api``, but with the engine's lifespan, so the categorization worker runs."""
    with TestClient(
        create_app(make_settings()),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        yield client


def settle(api: TestClient) -> None:
    """Wait until background categorization has finished everything asked of it so far."""
    worker = cast(FastAPI, api.app).state.categorization
    assert isinstance(worker, CategorizationWorker)
    assert worker.wait_until_idle(10.0)


def import_csv(api: TestClient, account_id: int, statement: bytes) -> dict[str, Any]:
    """Import a ``Date,Description,Amount`` CSV with the layout the engine detects."""
    preview = api.post("/imports/preview", files={"file": ("s.csv", statement)})
    assert preview.status_code == 200, preview.text
    response = api.post(
        "/imports",
        files={"file": ("s.csv", statement)},
        data={
            "account_id": str(account_id),
            "layout": json.dumps(preview.json()["csv"]["layout"]),
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def category_ids(api: TestClient) -> dict[str, int]:
    return {category["name"]: category["id"] for category in api.get("/categories").json()}


def all_transactions(api: TestClient) -> list[dict[str, Any]]:
    """Every stored transaction (up to one page of 500), newest first."""
    response = api.get("/transactions", params={"limit": 500})
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def transactions_by_description(api: TestClient) -> dict[str, dict[str, Any]]:
    """Every stored transaction by its bank description; for statements without repeats."""
    return {tx["description_raw"]: tx for tx in all_transactions(api)}
