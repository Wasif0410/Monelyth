from __future__ import annotations

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
    b"2026-09-01,MYSTERY SHOP 123,-12.00\n"
    b"2026-09-02,MYSTERY SHOP 123,-14.00\n"
    b"2026-09-03,UBER *TRIP,-23.18\n"
)


def _rules(api: TestClient) -> list[dict[str, Any]]:
    response = api.get("/rules")
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def _create(api: TestClient, **body: Any) -> dict[str, Any]:
    response = api.post("/rules", json=body)
    assert response.status_code == 201, response.text
    rule: dict[str, Any] = response.json()
    return rule


def test_lists_the_defaults_after_the_users_rules(api: TestClient) -> None:
    ids = category_ids(api)
    mine = _create(api, pattern="  blue  bottle ", category_id=ids["Coffee"])

    rules = _rules(api)

    assert mine == {
        "id": mine["id"],
        "pattern": "blue bottle",
        "match_type": "contains",
        "category_id": ids["Coffee"],
        "priority": 0,
        "created_by": "user",
    }
    assert rules[0] == mine
    assert len(rules) > 100
    assert {rule["created_by"] for rule in rules[1:]} == {"system"}
    eats = next(rule for rule in rules if rule["pattern"] == "uber eats")
    uber = next(rule for rule in rules if rule["pattern"] == "uber")
    assert rules.index(eats) < rules.index(uber)


def test_preview_counts_what_a_pattern_matches(api: TestClient) -> None:
    import_csv(api, create_account(api)["id"], STATEMENT)
    ids = category_ids(api)
    mystery = transactions_by_description(api)["MYSTERY SHOP 123"]
    api.patch(f"/transactions/{mystery['id']}", json={"category_id": ids["Other"]})

    response = api.post("/rules/preview", json={"pattern": "mystery shop"})

    assert response.status_code == 200, response.text
    assert response.json() == {"matching": 2, "user_set": 1, "examples": ["Mystery Shop"]}
    regex = api.post("/rules/preview", json={"pattern": r"^uber\b", "match_type": "regex"})
    assert regex.json()["matching"] == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"pattern": "  "}, "Enter the text the rule should look for."),
        ({"pattern": "(a+)+", "match_type": "regex"}, "could take too long to check"),
        ({"pattern": "uber(", "match_type": "regex"}, "isn't a valid regular expression"),
    ],
)
def test_an_unusable_pattern_is_explained(
    api: TestClient, body: dict[str, Any], message: str
) -> None:
    ids = category_ids(api)

    preview = api.post("/rules/preview", json=body)
    create = api.post("/rules", json={**body, "category_id": ids["Other"]})

    for response in (preview, create):
        assert response.status_code == 422
        assert message in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"pattern": "x"},
        {"pattern": "x", "category_id": 0},
        {"pattern": "x", "category_id": 1, "priority": -1},
        {"pattern": "x", "category_id": 1, "priority": 1001},
        {"pattern": "x", "category_id": 1, "match_type": "glob"},
        {"pattern": "x", "category_id": 1, "created_by": "system"},
        {"pattern": "x" * 1001, "category_id": 1},
    ],
)
def test_invalid_rule_requests(api: TestClient, body: dict[str, Any]) -> None:
    assert api.post("/rules", json=body).status_code == 422


def test_duplicates_and_unknown_categories(api: TestClient) -> None:
    ids = category_ids(api)
    _create(api, pattern="Blue Bottle", category_id=ids["Coffee"])

    duplicate = api.post("/rules", json={"pattern": "BLUE-BOTTLE", "category_id": ids["Other"]})
    unknown = api.post("/rules", json={"pattern": "new", "category_id": 999})

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"].startswith("You already have a rule for")
    assert unknown.status_code == 404


def test_edit_and_delete_the_users_rules_only(api: TestClient) -> None:
    ids = category_ids(api)
    mine = _create(api, pattern="lyft", category_id=ids["Rideshare"])
    system = next(rule for rule in _rules(api) if rule["created_by"] == "system")

    edited = api.patch(f"/rules/{mine['id']}", json={"priority": 7})
    assert edited.status_code == 200, edited.text
    assert edited.json() == {**mine, "priority": 7}

    refused = api.patch(f"/rules/{system['id']}", json={"priority": 7})
    assert refused.status_code == 403
    assert "can't be changed" in refused.json()["detail"]
    assert api.delete(f"/rules/{system['id']}").status_code == 403
    assert api.patch(f"/rules/{mine['id']}", json={}).status_code == 422
    assert api.patch("/rules/99999", json={"priority": 1}).status_code == 404

    deleted = api.delete(f"/rules/{mine['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert api.delete(f"/rules/{mine['id']}").status_code == 404


def _by_id(api: TestClient) -> dict[int, dict[str, Any]]:
    return {tx["id"]: tx for tx in all_transactions(api)}


def test_rule_changes_recategorize_but_never_the_users_choices(running_api: TestClient) -> None:
    api = running_api
    import_csv(api, create_account(api)["id"], STATEMENT)
    settle(api)
    ids = category_ids(api)
    first, second = sorted(
        (tx for tx in all_transactions(api) if "MYSTERY" in tx["description_raw"]),
        key=lambda tx: tx["posted_date"],
    )
    # The user's correction is remembered for the merchant...
    api.patch(f"/transactions/{first['id']}", json={"category_id": ids["Gifts & Donations"]})

    # ...until a rule for it takes over.
    rule = _create(api, pattern="mystery shop", category_id=ids["Shopping"])
    settle(api)
    txs = _by_id(api)
    assert (txs[second["id"]]["category_id"], txs[second["id"]]["category_source"]) == (
        ids["Shopping"],
        "rule",
    )
    assert txs[first["id"]]["category_id"] == ids["Gifts & Donations"]
    assert txs[first["id"]]["category_source"] == "user"

    api.patch(f"/rules/{rule['id']}", json={"category_id": ids["Entertainment"]})
    settle(api)
    assert _by_id(api)[second["id"]]["category_id"] == ids["Entertainment"]

    assert api.delete(f"/rules/{rule['id']}").status_code == 204
    settle(api)
    txs = _by_id(api)
    # Nothing answers for the merchant any more, so it waits for review.
    assert (txs[second["id"]]["category_id"], txs[second["id"]]["needs_review"]) == (None, True)
    assert txs[first["id"]]["category_id"] == ids["Gifts & Donations"]
    # The Uber trip was never matched, so it was never re-categorized.
    uber = next(tx for tx in txs.values() if tx["description_raw"] == "UBER *TRIP")
    assert (uber["category_id"], uber["category_source"]) == (ids["Rideshare"], "rule")
