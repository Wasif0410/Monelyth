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


def _import(api: TestClient, account_id: int, data: bytes = STATEMENT) -> None:
    preview = api.post("/imports/preview", files={"file": ("s.csv", data)}).json()
    response = api.post(
        "/imports",
        files={"file": ("s.csv", data)},
        data={"account_id": str(account_id), "layout": json.dumps(preview["csv"]["layout"])},
    )
    assert response.status_code == 201, response.text


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
        "transaction_count": 0,
        "latest_transaction_date": None,
        "net_amount_cents": 0,
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


def test_list_includes_each_accounts_transaction_stats(api: TestClient) -> None:
    checking = create_account(api)
    savings = create_account(api, name="Savings")
    _import(api, checking["id"])

    by_id = {account["id"]: account for account in api.get("/accounts").json()}

    assert by_id[checking["id"]]["transaction_count"] == 3
    assert by_id[checking["id"]]["latest_transaction_date"] == "2026-09-03"
    assert by_id[checking["id"]]["net_amount_cents"] == 200_000 - 525 - 8_210
    assert by_id[savings["id"]]["transaction_count"] == 0
    assert by_id[savings["id"]]["latest_transaction_date"] is None
    assert by_id[savings["id"]]["net_amount_cents"] == 0


def test_patch_renames_and_changes_the_institution(api: TestClient) -> None:
    account = create_account(api, institution="TD")
    _import(api, account["id"])

    response = api.patch(
        f"/accounts/{account['id']}", json={"name": "  Joint  ", "institution": " RBC "}
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated == account | {
        "name": "Joint",
        "institution": "RBC",
        "transaction_count": 3,
        "latest_transaction_date": "2026-09-03",
        "net_amount_cents": 191_265,
    }
    assert api.get("/accounts").json() == [updated]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"name": "Renamed"}, {"name": "Renamed", "institution": "TD"}),
        ({"institution": "RBC"}, {"name": "Main Checking", "institution": "RBC"}),
        ({"institution": None}, {"name": "Main Checking", "institution": None}),
        ({"institution": "  "}, {"name": "Main Checking", "institution": None}),
        ({}, {"name": "Main Checking", "institution": "TD"}),
    ],
)
def test_patch_changes_only_the_fields_given(
    api: TestClient, body: dict[str, Any], expected: dict[str, Any]
) -> None:
    account = create_account(api, institution="TD")

    response = api.patch(f"/accounts/{account['id']}", json=body)

    assert response.status_code == 200, response.text
    assert response.json() == account | expected


@pytest.mark.parametrize(
    "body",
    [
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"institution": "x" * 101},
        {"currency": "USD"},
        {"type": "savings"},
    ],
)
def test_invalid_patches_are_rejected(api: TestClient, body: dict[str, Any]) -> None:
    account = create_account(api)

    assert api.patch(f"/accounts/{account['id']}", json=body).status_code == 422
    assert api.get("/accounts").json() == [account]


def test_patch_missing_account_is_404(api: TestClient) -> None:
    response = api.patch("/accounts/42", json={"name": "Anything"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Account 42 does not exist"}


def test_delete_removes_the_account_with_its_imports_and_transactions(api: TestClient) -> None:
    account = create_account(api)
    other = create_account(api, name="Savings")
    _import(api, account["id"])

    response = api.delete(f"/accounts/{account['id']}")

    assert response.status_code == 200, response.text
    assert response.json() == {"deleted_imports": 1, "deleted_transactions": 3}
    assert api.get("/accounts").json() == [other]
    assert api.get("/transactions").json()["total"] == 0
    # The import record went too, so the same file can be imported again.
    _import(api, other["id"])
    assert api.get("/transactions").json()["total"] == 3


def test_delete_missing_account_is_404(api: TestClient) -> None:
    response = api.delete("/accounts/42")

    assert response.status_code == 404
    assert response.json() == {"detail": "Account 42 does not exist"}
