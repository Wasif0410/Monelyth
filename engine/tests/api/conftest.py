from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient

from monelyth_engine.app import create_app
from monelyth_engine.config import Settings
from tests.conftest import TOKEN

SAMPLE_DATA: Final = Path(__file__).resolve().parents[3] / "sample-data"


@pytest.fixture
def api(make_settings: Callable[..., Settings]) -> TestClient:
    """An authorized client for a fresh, empty database."""
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
