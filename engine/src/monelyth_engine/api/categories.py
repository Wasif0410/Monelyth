"""Spending and income categories."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from monelyth_engine.api.deps import Connection
from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.models import CategoryKind

router = APIRouter(prefix="/categories", tags=["categories"])


class CategoryOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    kind: CategoryKind
    parent_id: int | None


@router.get("")
def get_categories(conn: Connection) -> list[CategoryOut]:
    return [
        CategoryOut(id=c.id, name=c.name, kind=c.kind, parent_id=c.parent_id)
        for c in list_categories(conn)
    ]
