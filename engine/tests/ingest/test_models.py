from __future__ import annotations

import datetime

import pytest

from monelyth_engine.ingest.models import ParsedStatement, RawTransaction, StatementFormat


def test_raw_transaction_holds_values() -> None:
    tx = RawTransaction(datetime.date(2026, 9, 1), -1299, "SQ *BLUE BOTTLE", external_id="A1")

    assert tx.amount_cents == -1299
    assert tx.external_id == "A1"


@pytest.mark.parametrize("description", ["", " padded", "padded "])
def test_raw_transaction_rejects_bad_descriptions(description: str) -> None:
    with pytest.raises(ValueError, match="description"):
        RawTransaction(datetime.date(2026, 9, 1), -100, description)


def test_raw_transaction_rejects_empty_external_id() -> None:
    with pytest.raises(ValueError, match="external_id"):
        RawTransaction(datetime.date(2026, 9, 1), -100, "Coffee", external_id="")


def test_parsed_statement_defaults() -> None:
    statement = ParsedStatement(StatementFormat.CSV, ())

    assert statement.currency is None
    assert statement.warnings == ()
    assert str(StatementFormat.OFX) == "ofx"
