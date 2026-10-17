"""Liveness check used by the desktop shell and UI."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from monelyth_engine import __version__

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    version: str


@router.get("/health")
def get_health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
