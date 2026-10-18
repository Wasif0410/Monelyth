from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from monelyth_engine.config import Settings
from monelyth_engine.database import Database
from monelyth_engine.insights.transfers import link_transfers
from tests.api.conftest import create_account

CHECKING = b"Date,Description,Amount\n2026-09-22,ONLINE PAYMENT DEMO BANK VISA,-697.50\n"
CARD = b"Date,Description,Amount\n2026-09-23,PAYMENT - THANK YOU,697.50\n"


def _import(api: TestClient, account: dict[str, Any], name: str, data: bytes) -> None:
    preview = api.post("/imports/preview", files={"file": (name, data)}).json()
    response = api.post(
        "/imports",
        files={"file": (name, data)},
        data={"account_id": str(account["id"]), "layout": json.dumps(preview["csv"]["layout"])},
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def transfer_group(api: TestClient, make_settings: Callable[..., Settings]) -> str:
    """Two accounts holding both sides of a card payment, linked as a transfer."""
    _import(api, create_account(api), "checking.csv", CHECKING)
    card = create_account(api, name="Visa", type="credit_card")
    _import(api, card, "card.csv", CARD)
    # The pipeline runs this after an import; it has no route of its own.
    with Database(make_settings().data_dir).connection() as conn:
        assert link_transfers(conn) == 1
    items = api.get("/transactions").json()["items"]
    groups = {item["transfer_group"] for item in items}
    assert len(groups) == 1
    group = groups.pop()
    assert isinstance(group, str)
    return group


def test_unlinking_returns_both_transactions_uncategorized(
    api: TestClient, transfer_group: str
) -> None:
    response = api.delete(f"/transfers/{transfer_group}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["amount_cents"] for item in body] == [-69_750, 69_750]
    for item in body:
        assert item["transfer_group"] is None
        assert item["category_id"] is None
        assert item["category_source"] is None
        assert item["needs_review"] is True
    listed = api.get("/transactions", params={"needs_review": True}).json()
    assert listed["total"] == 2


def test_unlinking_twice_is_not_found(api: TestClient, transfer_group: str) -> None:
    assert api.delete(f"/transfers/{transfer_group}").status_code == 200

    response = api.delete(f"/transfers/{transfer_group}")

    assert response.status_code == 404
    assert response.json() == {"detail": "These transactions are no longer linked as a transfer."}


def test_an_overlong_group_is_rejected(api: TestClient) -> None:
    assert api.delete(f"/transfers/{'a' * 65}").status_code == 422
