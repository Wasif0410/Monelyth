from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from typing import Any

import pytest
from fastapi.testclient import TestClient

from monelyth_engine.app import create_app
from monelyth_engine.config import Settings
from monelyth_engine.database import DATABASE_FILE_NAME
from monelyth_engine.db.connection import connect
from tests.api.conftest import (
    category_ids,
    create_account,
    import_csv,
    settle,
    transactions_by_description,
)
from tests.conftest import TOKEN

STATEMENT = (
    b"Date,Description,Amount\n"
    b"2026-09-01,PAYROLL ACME CORP,2000.00\n"
    b"2026-09-02,SQ *BLUE BOTTLE 0423 TORONTO ON,-5.25\n"
    b"2026-09-03,MYSTERY SHOP 123,-12.00\n"
)


def _status(api: TestClient) -> dict[str, Any]:
    response = api.get("/categorization/status")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_an_import_is_categorized_in_the_background(running_api: TestClient) -> None:
    account = create_account(running_api)
    settle(running_api)
    runs_before = _status(running_api)["runs_finished"]

    import_csv(running_api, account["id"], STATEMENT)
    settle(running_api)

    ids = category_ids(running_api)
    txs = transactions_by_description(running_api)
    assert txs["PAYROLL ACME CORP"]["category_id"] == ids["Salary"]
    assert txs["PAYROLL ACME CORP"]["category_source"] == "rule"
    assert txs["SQ *BLUE BOTTLE 0423 TORONTO ON"]["category_id"] == ids["Coffee"]
    mystery = txs["MYSTERY SHOP 123"]
    assert (mystery["category_id"], mystery["needs_review"]) == (None, True)
    status = _status(running_api)
    assert status["state"] == "idle"
    assert status["runs_finished"] > runs_before
    assert (status["processed"], status["total"], status["last_error"]) == (3, 3, None)


def test_the_run_is_queued_before_the_import_response(api: TestClient) -> None:
    # Without the lifespan the worker never starts, so the queued run stays visible.
    assert _status(api)["state"] == "idle"
    account = create_account(api)

    import_csv(api, account["id"], STATEMENT)

    assert _status(api)["state"] == "queued"


def test_demo_data_is_categorized_too(api: TestClient) -> None:
    assert api.post("/demo", json={"currency": "CAD"}).status_code == 201

    assert _status(api)["state"] == "queued"


def test_a_failed_import_queues_nothing(api: TestClient) -> None:
    account = create_account(api)

    response = api.post(
        "/imports", files={"file": ("s.csv", STATEMENT)}, data={"account_id": str(account["id"])}
    )

    assert response.status_code == 422
    assert _status(api)["state"] == "idle"


def test_transactions_left_uncategorized_are_caught_up_at_startup(
    api: TestClient, make_settings: Callable[..., Settings]
) -> None:
    # Imported while no worker ran, as by an older version of the app.
    import_csv(api, create_account(api)["id"], STATEMENT)
    assert transactions_by_description(api)["PAYROLL ACME CORP"]["category_id"] is None

    with TestClient(
        create_app(make_settings()),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as restarted:
        settle(restarted)
        payroll = transactions_by_description(restarted)["PAYROLL ACME CORP"]
        assert payroll["category_id"] == category_ids(restarted)["Salary"]


@pytest.mark.parametrize(("scope", "fixed"), [("uncategorized", False), ("all", True)])
def test_run_on_demand(
    running_api: TestClient, make_settings: Callable[..., Settings], scope: str, fixed: bool
) -> None:
    import_csv(running_api, create_account(running_api)["id"], STATEMENT)
    settle(running_api)
    ids = category_ids(running_api)
    # An automatic category that is now wrong, e.g. from rules an older version shipped.
    with closing(connect(make_settings().data_dir / DATABASE_FILE_NAME)) as conn:
        conn.execute(
            "UPDATE transactions SET category_id = ? WHERE description_raw = 'PAYROLL ACME CORP'",
            (ids["Other"],),
        )

    response = running_api.post("/categorization/run", json={"scope": scope})

    assert response.status_code == 202, response.text
    assert response.json()["state"] in {"queued", "running", "idle"}
    settle(running_api)
    payroll = transactions_by_description(running_api)["PAYROLL ACME CORP"]
    assert payroll["category_id"] == (ids["Salary"] if fixed else ids["Other"])


def test_run_rejects_an_unknown_scope(api: TestClient) -> None:
    assert api.post("/categorization/run", json={"scope": "everything"}).status_code == 422


def test_a_preview_queues_nothing(api: TestClient) -> None:
    response = api.post("/imports/preview", files={"file": ("s.csv", STATEMENT)})

    assert response.status_code == 200
    assert _status(api)["state"] == "idle"
