"""Where the engine keeps its database, and how request handlers get a connection to it."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from monelyth_engine.db.connection import connect

DATABASE_FILE_NAME: Final = "monelyth.db"


class Database:
    """The user's database file inside the engine's data folder.

    Each request opens its own connection. SQLite connections must not be shared between
    threads, and FastAPI runs request handlers on a thread pool; opening one is cheap, and WAL
    mode lets one write and several reads happen at the same time.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self.path: Final = data_dir / DATABASE_FILE_NAME

    def initialize(self) -> None:
        """Create the data folder and database if needed and bring the schema up to date.

        Run at startup so a database the engine can't open stops it before it reports ready,
        instead of failing on the first request.

        Raises:
            SchemaVersionError: if the database was created by a newer version of Monelyth.
            sqlite3.Error: if the file cannot be opened or is not a database.
            OSError: if the data folder cannot be created.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        connect(self.path).close()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        """A connection for one request.

        FastAPI runs a request's dependencies and its handler on worker threads that can
        differ, so the connection may be opened on one thread and used on another. That is
        safe because a request uses it from one thread at a time, so the thread check is off.
        """
        conn = connect(self.path, check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()
