"""Dependencies shared by the route modules."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request

from monelyth_engine.database import Database


def get_database(request: Request) -> Database:
    # Set by create_app; Starlette types app.state as Any.
    return cast(Database, request.app.state.database)


def get_connection(
    database: Annotated[Database, Depends(get_database)],
) -> Iterator[sqlite3.Connection]:
    """A connection for one request, closed when the response has been sent."""
    with database.connection() as conn:
        yield conn


Connection = Annotated[sqlite3.Connection, Depends(get_connection)]
