from __future__ import annotations

import threading
from pathlib import Path

from monelyth_engine.database import Database


def test_request_connection_can_be_used_from_another_thread(tmp_path: Path) -> None:
    """Regression: FastAPI may open a request's connection and run its handler on different
    worker threads; Python's default same-thread check made that fail in the real app."""
    database = Database(tmp_path / "data")
    database.initialize()
    errors: list[BaseException] = []
    counts: list[int] = []

    with database.connection() as conn:

        def use_connection() -> None:
            try:
                counts.append(conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0])
            except BaseException as error:  # reported through the list below
                errors.append(error)

        worker = threading.Thread(target=use_connection)
        worker.start()
        worker.join()

    assert errors == []
    assert counts[0] > 0
