from __future__ import annotations

import datetime
import sqlite3
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient

from monelyth_engine.api import demo as demo_api
from monelyth_engine.demo import Month, generate
from monelyth_engine.demo import loader as loader_module
from monelyth_engine.ingest.csv_statement import CsvLayout
from monelyth_engine.normalize import normalize_merchant
from monelyth_engine.services.importing import ImportOutcome, StatementFile
from tests.api.conftest import create_account

TODAY: Final = datetime.date(2026, 10, 17)
EXPECTED: Final = generate(Month.of(TODAY)).through(TODAY)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_api, "_today", lambda: TODAY)


def _add_demo(api: TestClient, currency: str = "CAD") -> dict[str, Any]:
    response = api.post("/demo", json={"currency": currency})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _all_transactions(api: TestClient, account_id: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        page = api.get(
            "/transactions", params={"account_id": account_id, "limit": 500, "offset": len(items)}
        ).json()
        items += page["items"]
        if len(items) >= page["total"]:
            return items


def test_creates_two_accounts_with_a_year_of_transactions(api: TestClient) -> None:
    body = _add_demo(api)

    checking, card = body["accounts"]
    assert checking == {
        "id": checking["id"],
        "name": "Demo Checking",
        "institution": None,
        "type": "checking",
        "currency": "CAD",
    }
    assert card == {
        "id": card["id"],
        "name": "Demo Visa",
        "institution": None,
        "type": "credit_card",
        "currency": "CAD",
    }
    assert api.get("/accounts").json() == body["accounts"]
    checking_import, card_import = body["imports"]
    assert checking_import == {
        "import_id": checking_import["import_id"],
        "account_id": checking["id"],
        "file_name": "monelyth-demo-checking-2026-10-17.csv",
        "format": "csv",
        "added": len(EXPECTED.checking),
        "skipped_duplicates": 0,
        "warnings": [],
    }
    assert card_import["account_id"] == card["id"]
    assert card_import["added"] == len(EXPECTED.card)
    assert card_import["skipped_duplicates"] == 0
    assert body["transactions_added"] == len(EXPECTED.checking) + len(EXPECTED.card)
    assert api.get("/transactions").json()["total"] == body["transactions_added"]


def test_transactions_are_cleaned_and_stored(api: TestClient) -> None:
    checking, card = _add_demo(api)["accounts"]

    for account, rows in ((checking, EXPECTED.checking), (card, EXPECTED.card)):
        stored = _all_transactions(api, account["id"])
        assert sorted(
            (tx["posted_date"], tx["description_raw"], tx["amount_cents"]) for tx in stored
        ) == sorted((row.posted.isoformat(), row.description, row.amount_cents) for row in rows)
        for tx in stored:
            assert tx["merchant"] == normalize_merchant(tx["description_raw"])
            assert tx["posted_date"] <= TODAY.isoformat()
    rent = next(
        tx
        for tx in _all_transactions(api, checking["id"])
        if "HARBOURVIEW" in tx["description_raw"]
    )
    assert "PREAUTHORIZED" not in rent["merchant"]


def test_uses_the_chosen_currency(api: TestClient) -> None:
    body = _add_demo(api, "EUR")

    assert [account["currency"] for account in body["accounts"]] == ["EUR", "EUR"]


def test_a_second_call_is_refused(api: TestClient) -> None:
    first = _add_demo(api)

    response = api.post("/demo", json={"currency": "CAD"})

    assert response.status_code == 409
    assert "already been added" in response.json()["detail"]
    assert api.get("/accounts").json() == first["accounts"]
    assert api.get("/transactions").json()["total"] == first["transactions_added"]


def test_the_users_own_accounts_are_kept(api: TestClient) -> None:
    own = create_account(api)

    body = _add_demo(api)

    assert api.get("/accounts").json() == [own, *body["accounts"]]


@pytest.mark.parametrize(
    "payload",
    [{}, {"currency": "cad"}, {"currency": "CA"}, {"currency": "CAD", "extra": True}],
)
def test_invalid_requests_are_rejected(api: TestClient, payload: dict[str, Any]) -> None:
    response = api.post("/demo", json=payload)

    assert response.status_code == 422
    assert api.get("/accounts").json() == []


def test_is_atomic(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    real_commit = loader_module.commit_import
    calls = 0

    def fail_on_the_card(
        conn: sqlite3.Connection,
        *,
        account_id: int,
        file: StatementFile,
        layout: CsvLayout | None,
    ) -> ImportOutcome:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("disk full")
        return real_commit(conn, account_id=account_id, file=file, layout=layout)

    monkeypatch.setattr(loader_module, "commit_import", fail_on_the_card)
    with pytest.raises(RuntimeError, match="disk full"):
        api.post("/demo", json={"currency": "CAD"})

    assert calls == 2
    assert api.get("/accounts").json() == []
    assert api.get("/transactions").json()["total"] == 0

    monkeypatch.setattr(loader_module, "commit_import", real_commit)
    assert _add_demo(api)["transactions_added"] == len(EXPECTED.checking) + len(EXPECTED.card)
