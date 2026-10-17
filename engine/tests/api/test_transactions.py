from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import create_account

STATEMENT = (
    b"Date,Description,Amount\n"
    b"2026-09-01,PAYROLL ACME CORP,2000.00\n"
    b"2026-09-02,SQ *BLUE BOTTLE 0423 TORONTO ON,-5.25\n"
    b"2026-09-03,POS PURCHASE LOBLAWS #1031 TORONTO ON,-82.10\n"
)


@pytest.fixture
def seeded(api: TestClient) -> dict[str, Any]:
    account = create_account(api)
    preview = api.post("/imports/preview", files={"file": ("s.csv", STATEMENT)}).json()
    response = api.post(
        "/imports",
        files={"file": ("s.csv", STATEMENT)},
        data={"account_id": str(account["id"]), "layout": json.dumps(preview["csv"]["layout"])},
    )
    assert response.status_code == 201, response.text
    return account


def _list(api: TestClient, **params: Any) -> dict[str, Any]:
    response = api.get("/transactions", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_list_is_newest_first_with_cleaned_merchants(
    api: TestClient, seeded: dict[str, Any]
) -> None:
    page = _list(api)

    assert page["total"] == 3
    assert [tx["posted_date"] for tx in page["items"]] == ["2026-09-03", "2026-09-02", "2026-09-01"]
    assert [tx["merchant"] for tx in page["items"]][:2] == ["Loblaws", "Blue Bottle"]
    assert page["items"][0]["account_id"] == seeded["id"]
    assert page["items"][0]["amount_cents"] == -8210


def test_filters_and_pagination(api: TestClient, seeded: dict[str, Any]) -> None:
    assert _list(api, q="blue bottle")["total"] == 1
    assert _list(api, date_from="2026-09-02", date_to="2026-09-02")["total"] == 1
    assert _list(api, account_id=seeded["id"] + 1)["total"] == 0
    page = _list(api, limit=2, offset=2)
    assert page["total"] == 3
    assert len(page["items"]) == 1


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 501}, {"offset": -1}, {"date_from": "yesterday"}, {"account_id": 0}],
)
def test_invalid_list_parameters(
    api: TestClient, seeded: dict[str, Any], params: dict[str, Any]
) -> None:
    assert api.get("/transactions", params=params).status_code == 422


def test_user_can_set_category_and_merchant(api: TestClient, seeded: dict[str, Any]) -> None:
    tx = _list(api)["items"][0]
    groceries = next(c for c in api.get("/categories").json() if c["name"] == "Groceries")

    response = api.patch(
        f"/transactions/{tx['id']}",
        json={"category_id": groceries["id"], "merchant": "  Loblaws Queen St  "},
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["category_id"] == groceries["id"]
    assert updated["category_source"] == "user"
    assert updated["merchant"] == "Loblaws Queen St"
    assert updated["needs_review"] is False


@pytest.mark.parametrize(
    "body", [{}, {"merchant": "   "}, {"category_id": 0}, {"category_id": 1, "x": 1}]
)
def test_invalid_updates_are_rejected(
    api: TestClient, seeded: dict[str, Any], body: dict[str, Any]
) -> None:
    tx = _list(api)["items"][0]

    assert api.patch(f"/transactions/{tx['id']}", json=body).status_code == 422


def test_unknown_transaction_or_category_is_404(api: TestClient, seeded: dict[str, Any]) -> None:
    tx = _list(api)["items"][0]

    assert api.patch("/transactions/999999", json={"merchant": "X"}).status_code == 404
    assert api.patch(f"/transactions/{tx['id']}", json={"category_id": 999}).status_code == 404
