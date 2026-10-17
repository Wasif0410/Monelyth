from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import create_account


def test_accounts_start_empty(api: TestClient) -> None:
    response = api.get("/accounts")

    assert response.status_code == 200
    assert response.json() == []


def test_create_and_list_accounts(api: TestClient) -> None:
    created = create_account(api, name="  Everyday  ", institution=" Demo Bank ")

    assert created == {
        "id": created["id"],
        "name": "Everyday",
        "institution": "Demo Bank",
        "type": "checking",
        "currency": "CAD",
    }
    assert api.get("/accounts").json() == [created]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "type": "checking", "currency": "CAD"},
        {"name": "   ", "type": "checking", "currency": "CAD"},
        {"name": "x" * 101, "type": "checking", "currency": "CAD"},
        {"name": "A", "type": "brokerage", "currency": "CAD"},
        {"name": "A", "type": "checking", "currency": "cad"},
        {"name": "A", "type": "checking", "currency": "CA"},
        {"name": "A", "type": "checking"},
        {"name": "A", "type": "checking", "currency": "CAD", "unknown": 1},
    ],
)
def test_invalid_accounts_are_rejected(api: TestClient, body: dict[str, object]) -> None:
    assert api.post("/accounts", json=body).status_code == 422
