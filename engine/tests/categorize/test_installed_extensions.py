"""The tiers and pre-passes the app actually runs, and how optional tiers are cleaned up."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import pytest

from monelyth_engine.categorize import tiers as tiers_module
from monelyth_engine.categorize.models import CategorizationInput, Suggestion
from monelyth_engine.categorize.pipeline import UNPROCESSED, run_categorization
from monelyth_engine.categorize.tiers import (
    PipelineExtensions,
    TransferLinking,
    close_tiers,
    installed_extensions,
)
from monelyth_engine.db.models import Category, CategorySource
from monelyth_engine.llm.config import MODEL_ENV_VAR, URL_ENV_VAR


class ClosingTier:
    """A tier that holds a resource and records whether it was released."""

    def __init__(self, *, fail: bool = False) -> None:
        self.closed = False
        self._fail = fail

    @property
    def source(self) -> CategorySource:
        return CategorySource.LLM

    def suggest(
        self, items: Sequence[CategorizationInput], categories: Sequence[Category]
    ) -> list[Suggestion | None]:
        if self._fail:
            raise RuntimeError("server went away")
        return [None for _ in items]

    def close(self) -> None:
        self.closed = True


def test_app_links_transfers_before_the_tiers() -> None:
    extensions = installed_extensions()

    assert [type(p) for p in extensions.pre_passes] == [TransferLinking]
    assert extensions.pre_passes[0].name == "Transfer detection"


def test_transfer_pre_pass_calls_link_transfers(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[sqlite3.Connection] = []

    def fake_link_transfers(conn: sqlite3.Connection) -> int:
        calls.append(conn)
        return 0

    monkeypatch.setattr(tiers_module, "link_transfers", fake_link_transfers)

    TransferLinking().run(db)

    assert calls == [db]


def test_no_optional_tiers_without_a_configured_llm(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(URL_ENV_VAR, raising=False)
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
    factory = installed_extensions().optional_tiers
    assert factory is not None

    assert list(factory(db)) == []


@pytest.mark.parametrize("fail", [False, True])
def test_run_closes_optional_tiers(db: sqlite3.Connection, fail: bool) -> None:
    tier = ClosingTier(fail=fail)

    run_categorization(
        db, UNPROCESSED, extensions=PipelineExtensions(optional_tiers=lambda _conn: [tier])
    )

    assert tier.closed


def test_close_tiers_keeps_going_when_one_fails(caplog: pytest.LogCaptureFixture) -> None:
    class Broken(ClosingTier):
        def close(self) -> None:
            raise OSError("socket already gone")

    healthy = ClosingTier()

    close_tiers([Broken(), healthy])

    assert healthy.closed
    assert "Could not close" in caplog.text
