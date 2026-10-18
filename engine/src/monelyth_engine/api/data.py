"""Where the user's data lives, exporting all of it, and erasing all of it."""

from __future__ import annotations

import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from monelyth_engine.api.deps import Connection, get_database
from monelyth_engine.database import Database
from monelyth_engine.db.maintenance import erase_all_data
from monelyth_engine.services.data_management import ExportError, export_everything, system_info

router = APIRouter(tags=["data"])

_Folder = Annotated[str, StringConstraints(min_length=1, max_length=4096)]


class SystemInfoOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    engine_version: str
    data_folder: str
    database_path: str
    database_size_bytes: int
    """The database file plus its write-ahead log."""
    account_count: int
    transaction_count: int


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: _Folder
    """Full path of an existing folder; the export is written to a new folder inside it."""


class ExportOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    """The new folder holding the export."""
    transaction_count: int


class EraseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: Literal["DELETE"]
    """Must be exactly ``DELETE``, as the user typed it to confirm."""


class EraseOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    deleted_accounts: int
    deleted_transactions: int


@router.get("/system/info")
def get_system_info(
    conn: Connection, database: Annotated[Database, Depends(get_database)]
) -> SystemInfoOut:
    info = system_info(conn, database.path)
    return SystemInfoOut(
        engine_version=info.engine_version,
        data_folder=str(info.data_folder),
        database_path=str(info.database_path),
        database_size_bytes=info.database_size_bytes,
        account_count=info.counts.accounts,
        transaction_count=info.counts.transactions,
    )


@router.post("/data/export", status_code=status.HTTP_201_CREATED)
def post_export(body: ExportRequest, conn: Connection) -> ExportOut:
    """Write a copy of the database, a CSV of every transaction and a README to a new folder."""
    try:
        result = export_everything(conn, body.folder, now=datetime.datetime.now().astimezone())
    except ExportError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return ExportOut(path=str(result.folder), transaction_count=result.transaction_count)


@router.post("/data/erase")
def post_erase(body: EraseRequest, conn: Connection) -> EraseOut:
    """Delete every account, import, transaction and learned setting, leaving a new database.

    The body is only validated: anything but `{"confirm": "DELETE"}` is rejected with 422.
    """
    counts = erase_all_data(conn)
    return EraseOut(deleted_accounts=counts.accounts, deleted_transactions=counts.transactions)
