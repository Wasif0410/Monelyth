from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from typing import Any

import pytest
from fastapi.testclient import TestClient

from monelyth_engine.config import Settings
from monelyth_engine.database import DATABASE_FILE_NAME
from monelyth_engine.db.connection import connect
from tests.api.conftest import category_ids, create_account, import_csv, transactions_by_description

STATEMENT = (
    b"Date,Description,Amount\n"
    b"2026-09-01,CORNER BAKERY,-8.00\n"
    b"2026-09-02,RIVERSIDE BOOKS,-21.00\n"
    b"2026-09-03,MYSTERY SHOP 123,-12.00\n"
)


@pytest.fixture
def queue(api: TestClient, make_settings: Callable[..., Settings]) -> dict[str, dict[str, Any]]:
    """Two low-confidence suggestions and one transaction no tier answered, as a classifier
    run would leave them."""
    account = create_account(api)
    import_csv(api, account["id"], STATEMENT)
    ids = category_ids(api)
    with closing(connect(make_settings().data_dir / DATABASE_FILE_NAME)) as conn:
        for description, category in (
            ("CORNER BAKERY", "Dining Out"),
            ("RIVERSIDE BOOKS", "Shopping"),
        ):
            conn.execute(
                "UPDATE transactions SET category_id = ?, category_source = 'classifier', "
                "confidence = 0.6, needs_review = 1 WHERE description_raw = ?",
                (ids[category], description),
            )
        conn.execute(
            "UPDATE transactions SET needs_review = 1 WHERE description_raw = 'MYSTERY SHOP 123'"
        )
    return transactions_by_description(api)


def _summary(api: TestClient) -> dict[str, int]:
    response = api.get("/review/summary")
    assert response.status_code == 200, response.text
    body: dict[str, int] = response.json()
    return body


def test_summary_counts_the_queue(api: TestClient, queue: dict[str, dict[str, Any]]) -> None:
    assert _summary(api) == {"waiting": 3, "with_suggestion": 2}


def test_accepting_one_makes_it_the_users_choice(
    api: TestClient, queue: dict[str, dict[str, Any]]
) -> None:
    bakery = queue["CORNER BAKERY"]

    response = api.post(
        "/review/accept",
        json={"transaction_ids": [bakery["id"], queue["MYSTERY SHOP 123"]["id"]]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"accepted": 1}
    after = transactions_by_description(api)["CORNER BAKERY"]
    assert after == {
        **bakery,
        "category_source": "user",
        "confidence": None,
        "needs_review": False,
    }
    assert _summary(api) == {"waiting": 2, "with_suggestion": 1}


def test_accept_all_takes_the_current_filters(
    api: TestClient, queue: dict[str, dict[str, Any]]
) -> None:
    filtered = api.post("/review/accept-all", json={"q": "books", "date_from": "2026-09-01"})
    assert filtered.json() == {"accepted": 1}

    everything = api.post("/review/accept-all", json={})
    assert everything.json() == {"accepted": 1}
    assert _summary(api) == {"waiting": 1, "with_suggestion": 0}


@pytest.mark.parametrize(
    "body",
    [
        {"transaction_ids": []},
        {"transaction_ids": [0]},
        {"transaction_ids": list(range(1, 1002))},
        {},
    ],
)
def test_invalid_accept_requests(api: TestClient, body: dict[str, Any]) -> None:
    assert api.post("/review/accept", json=body).status_code == 422


@pytest.mark.parametrize("body", [{"account_id": 0}, {"needs_review": False}, {"q": "x" * 201}])
def test_invalid_accept_all_requests(api: TestClient, body: dict[str, Any]) -> None:
    assert api.post("/review/accept-all", json=body).status_code == 422
