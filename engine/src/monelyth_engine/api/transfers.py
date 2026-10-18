"""Transfers between the user's own accounts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from monelyth_engine.api.deps import Connection
from monelyth_engine.api.transactions import TransactionOut
from monelyth_engine.insights.transfers import unlink_transfer

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.delete("/{transfer_group}")
def delete_transfer(
    transfer_group: Annotated[str, Path(min_length=1, max_length=64)], conn: Connection
) -> list[TransactionOut]:
    """Unlink two transactions that were wrongly paired as a transfer; returns both, updated.

    A side that was in Transfers only because of the link becomes uncategorized and needs
    review; a category the user chose stays.
    """
    return [TransactionOut.of(tx) for tx in unlink_transfer(conn, transfer_group)]
