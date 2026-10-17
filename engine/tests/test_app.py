from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from monelyth_engine import __version__
from monelyth_engine.app import create_app
from monelyth_engine.config import Settings
from tests.conftest import ALLOWED_ORIGIN, TOKEN


def test_health_with_valid_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/health", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_bearer_scheme_is_case_insensitive(client: TestClient) -> None:
    response = client.get("/health", headers={"Authorization": f"bearer {TOKEN}"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"Authorization": f"Bearer {TOKEN[:-1]}"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": TOKEN},
        {"Authorization": "Bearer "},
    ],
)
def test_requests_without_valid_token_are_rejected(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/health", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Unauthorized"}


def test_duplicate_authorization_headers_are_rejected(client: TestClient) -> None:
    headers = [("Authorization", f"Bearer {TOKEN}"), ("Authorization", f"Bearer {TOKEN}")]

    response = client.get("/health", headers=headers)

    assert response.status_code == 401


def test_unknown_route_does_not_reveal_itself_without_token(client: TestClient) -> None:
    assert client.get("/no-such-route").status_code == 401


def test_docs_and_schema_are_not_served(client: TestClient, auth_headers: dict[str, str]) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=auth_headers).status_code == 404


def test_non_loopback_host_header_is_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/health", headers={**auth_headers, "Host": "evil.example"})

    assert response.status_code == 400


def test_cors_preflight_from_allowed_origin(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


def test_cors_preflight_from_other_origin_is_refused(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers


def test_unauthorized_response_still_carries_cors_headers(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


def test_websocket_without_token_is_closed(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect("ws://127.0.0.1/health"),
    ):
        pass

    assert excinfo.value.code == 1008  # policy violation


def test_openapi_schema_is_available_in_process(make_settings: Callable[..., Settings]) -> None:
    schema = create_app(make_settings()).openapi()

    assert "/health" in schema["paths"]
