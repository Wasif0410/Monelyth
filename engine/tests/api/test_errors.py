from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from monelyth_engine.api.errors import UNEXPECTED_ERROR_MESSAGE
from monelyth_engine.app import create_app
from monelyth_engine.config import Settings
from tests.conftest import ALLOWED_ORIGIN, TOKEN


def test_unexpected_error_is_a_readable_500_with_cors_headers(
    make_settings: Callable[..., Settings], caplog: pytest.LogCaptureFixture
) -> None:
    """Regression: a bare 500 had no CORS headers, so the UI only saw "Failed to fetch"."""
    app = create_app(make_settings())

    def broken() -> None:
        raise RuntimeError("boom")

    app.router.add_api_route("/broken", broken)
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)

    response = client.get(
        "/broken", headers={"Authorization": f"Bearer {TOKEN}", "Origin": ALLOWED_ORIGIN}
    )

    assert response.status_code == 500
    assert response.json() == {"detail": UNEXPECTED_ERROR_MESSAGE}
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert "boom" in caplog.text
