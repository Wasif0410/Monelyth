from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import (
    all_transactions,
    category_ids,
    create_account,
    import_csv,
    settle,
    transactions_by_description,
)

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


def test_filters_by_category_state_and_review_flag(api: TestClient, seeded: dict[str, Any]) -> None:
    tx = _list(api)["items"][0]
    groceries = next(c for c in api.get("/categories").json() if c["name"] == "Groceries")
    response = api.patch(f"/transactions/{tx['id']}", json={"category_id": groceries["id"]})
    assert response.status_code == 200, response.text

    assert [t["id"] for t in _list(api, categorized="true")["items"]] == [tx["id"]]
    assert _list(api, categorized="false")["total"] == 2
    assert _list(api, categorized="false", category_id=groceries["id"])["total"] == 0
    # Background categorization doesn't run in these tests, so nothing is flagged.
    assert _list(api, needs_review="true")["total"] == 0
    assert _list(api, needs_review="false")["total"] == 3


def test_range_is_empty_without_transactions(api: TestClient) -> None:
    response = api.get("/transactions/range")

    assert response.status_code == 200, response.text
    assert response.json() == {"first_date": None, "last_date": None}


def test_range_spans_the_stored_transactions(api: TestClient, seeded: dict[str, Any]) -> None:
    assert api.get("/transactions/range").json() == {
        "first_date": "2026-09-01",
        "last_date": "2026-09-03",
    }


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
        {"date_from": "yesterday"},
        {"account_id": 0},
        {"categorized": "maybe"},
        {"needs_review": "maybe"},
    ],
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


BLUE_BOTTLES = (
    b"Date,Description,Amount\n"
    b"2026-09-01,SQ *BLUE BOTTLE 0423 TORONTO ON,-5.25\n"
    b"2026-09-02,BLUE BOTTLE COFFEE ONLINE,-24.00\n"
    b"2026-09-03,SQ *BLUE BOTTLE 0423 TORONTO ON,-4.75\n"
    b"2026-09-04,SQ *BLUE BOTTLE 0423 TORONTO ON,-6.10\n"
)


def test_a_correction_is_learned_for_later_imports(running_api: TestClient) -> None:
    api = running_api
    account = create_account(api)
    import_csv(api, account["id"], STATEMENT)
    settle(api)
    ids = category_ids(api)
    blue_bottle = transactions_by_description(api)["SQ *BLUE BOTTLE 0423 TORONTO ON"]
    assert blue_bottle["category_id"] == ids["Coffee"]

    response = api.patch(
        f"/transactions/{blue_bottle['id']}", json={"category_id": ids["Dining Out"]}
    )
    assert response.status_code == 200, response.text
    later = b"Date,Description,Amount\n2026-10-01,BLUE BOTTLE #12 MONTREAL QC,-6.00\n"
    import_csv(api, account["id"], later)
    settle(api)

    newest = all_transactions(api)[0]
    # The user's correction now beats the default "blue bottle" rule.
    assert (newest["category_id"], newest["category_source"]) == (ids["Dining Out"], "memory")


def test_same_merchant_and_apply(api: TestClient) -> None:
    import_csv(api, create_account(api)["id"], BLUE_BOTTLES)
    ids = category_ids(api)
    rows = sorted(all_transactions(api), key=lambda tx: tx["posted_date"])
    first, online, third, fourth = rows
    api.patch(f"/transactions/{fourth['id']}", json={"category_id": ids["Groceries"]})
    api.patch(f"/transactions/{first['id']}", json={"category_id": ids["Coffee"]})

    same = api.get(f"/transactions/{first['id']}/same-merchant")
    assert same.status_code == 200, same.text
    # The online store is a different merchant; the fourth is the user's own choice.
    assert same.json() == {"merchant": "Blue Bottle", "count": 1}

    applied = api.post(f"/transactions/{first['id']}/same-merchant/apply")
    assert applied.status_code == 200, applied.text
    assert applied.json() == {"updated": 1}
    after = {tx["id"]: tx for tx in all_transactions(api)}
    assert (after[third["id"]]["category_id"], after[third["id"]]["category_source"]) == (
        ids["Coffee"],
        "memory",
    )
    assert after[fourth["id"]]["category_id"] == ids["Groceries"]
    assert after[online["id"]]["category_id"] is None
    assert api.get(f"/transactions/{first['id']}/same-merchant").json()["count"] == 0


def test_apply_needs_a_category_and_a_transaction(api: TestClient) -> None:
    import_csv(api, create_account(api)["id"], BLUE_BOTTLES)
    tx = all_transactions(api)[0]

    refused = api.post(f"/transactions/{tx['id']}/same-merchant/apply")

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "This transaction has no category yet, so there's nothing to apply."
    )
    assert api.get("/transactions/99999/same-merchant").status_code == 404
    assert api.post("/transactions/99999/same-merchant/apply").status_code == 404
