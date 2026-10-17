from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from monelyth_engine.app import create_app
from monelyth_engine.config import Settings

TOKEN = "t" * 48
ALLOWED_ORIGIN = "http://tauri.localhost"


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "data_dir": tmp_path / "data",
            "token": TOKEN,
            "port": 0,
            "allowed_origins": (ALLOWED_ORIGIN,),
            "exit_on_stdin_eof": False,
            "log_level": "info",
        }
        values.update(overrides)
        return Settings(**values)

    return factory


@pytest.fixture
def client(make_settings: Callable[..., Settings]) -> TestClient:
    # The base URL uses loopback so the trusted-host check sees a real-looking Host header.
    return TestClient(create_app(make_settings()), base_url="http://127.0.0.1")


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}
