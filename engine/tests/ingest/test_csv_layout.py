from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

import pytest

from monelyth_engine.ingest.csv_layout import (
    LAYOUT_VERSION,
    CsvLayout,
    CsvLayoutDraft,
    CsvLayoutError,
    DebitCredit,
    SignedAmount,
)

SIGNED = CsvLayout(
    encoding="utf-8-sig",
    delimiter=",",
    skip_rows=0,
    has_header=True,
    date_column=0,
    description_column=1,
    amount=SignedAmount(2),
    date_format="%Y-%m-%d",
    decimal_separator=".",
    invert_signs=False,
)
DEBIT_CREDIT = CsvLayout(
    encoding="cp1252",
    delimiter=";",
    skip_rows=4,
    has_header=False,
    date_column=3,
    description_column=0,
    amount=DebitCredit(debit_column=1, credit_column=2),
    date_format="%d.%m.%Y",
    decimal_separator=",",
    invert_signs=True,
)


def _saved(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = dict(SIGNED.to_dict())
    data.update(overrides)
    return data


@pytest.mark.parametrize("layout", [SIGNED, DEBIT_CREDIT])
def test_layout_round_trips_through_json(layout: CsvLayout) -> None:
    stored = json.dumps(layout.to_dict())

    assert CsvLayout.from_dict(json.loads(stored)) == layout


def test_to_dict_shape() -> None:
    assert DEBIT_CREDIT.to_dict() == {
        "version": LAYOUT_VERSION,
        "encoding": "cp1252",
        "delimiter": ";",
        "skip_rows": 4,
        "has_header": False,
        "date_column": 3,
        "description_column": 0,
        "amount": {"kind": "debit_credit", "debit_column": 1, "credit_column": 2},
        "date_format": "%d.%m.%Y",
        "decimal_separator": ",",
        "invert_signs": True,
    }
    assert SIGNED.to_dict()["amount"] == {"kind": "signed", "column": 2}


def test_tab_delimiter_round_trips() -> None:
    layout = dataclasses.replace(SIGNED, delimiter="\t")

    assert CsvLayout.from_dict(json.loads(json.dumps(layout.to_dict()))) == layout


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (None, "'layout' must be an object"),
        ([1, 2], "'layout' must be an object"),
        ("{}", "'layout' must be an object"),
        (_saved(extra=1), "unknown keys: 'extra'"),
        ({k: v for k, v in SIGNED.to_dict().items() if k != "date_column"}, "missing keys"),
        (_saved(version=2), "unsupported layout version 2"),
        (_saved(version=True), "unsupported layout version True"),
        (_saved(version="1"), "unsupported layout version '1'"),
        (_saved(encoding="utf-16"), "'encoding' must be one of"),
        (_saved(encoding=None), "'encoding' must be one of"),
        (_saved(delimiter="|"), "'delimiter' must be one of"),
        (_saved(skip_rows=-1), "'skip_rows' must be a whole number from 0 to 100"),
        (_saved(skip_rows=101), "'skip_rows' must be a whole number"),
        (_saved(skip_rows=True), "'skip_rows' must be a whole number"),
        (_saved(skip_rows="1"), "'skip_rows' must be a whole number"),
        (_saved(skip_rows=1.0), "'skip_rows' must be a whole number"),
        (_saved(skip_rows=10**100), "'skip_rows' must be a whole number"),
        (_saved(has_header=1), "'has_header' must be true or false"),
        (_saved(date_column=64), "'date_column' must be a whole number from 0 to 63"),
        (_saved(description_column=False), "'description_column' must be a whole number"),
        (_saved(description_column=0), "must all be different"),
        (_saved(amount=None), "'amount' must be an object"),
        (_saved(amount=[2]), "'amount' must be an object"),
        (_saved(amount={"kind": "both", "column": 2}), "'amount.kind' must be"),
        (_saved(amount={"column": 2}), "'amount.kind' must be"),
        (_saved(amount={"kind": "signed", "column": 2, "x": 1}), "unknown keys: 'x'"),
        (_saved(amount={"kind": "signed"}), "missing keys: column"),
        (_saved(amount={"kind": "signed", "column": -1}), "'column' must be a whole number"),
        (_saved(amount={"kind": "signed", "column": 1}), "must all be different"),
        (
            _saved(amount={"kind": "debit_credit", "debit_column": 2, "credit_column": 2}),
            "debit and credit columns must be different",
        ),
        (_saved(date_format="%H:%M"), "'date_format' is not a supported value"),
        (_saved(date_format="%Y-%m-%d%n"), "'date_format' is not a supported value"),
        (_saved(decimal_separator=" "), "'decimal_separator' must be one of"),
        (_saved(invert_signs="yes"), "'invert_signs' must be true or false"),
    ],
)
def test_from_dict_rejects_bad_input(data: object, message: str) -> None:
    with pytest.raises(CsvLayoutError, match=re.escape(message)):
        CsvLayout.from_dict(data)


def test_from_dict_keeps_hostile_keys_out_of_the_message() -> None:
    with pytest.raises(CsvLayoutError) as caught:
        CsvLayout.from_dict(_saved(**{"k" * 10_000: 1}))

    assert len(str(caught.value)) < 200


def test_constructor_validates_too() -> None:
    with pytest.raises(CsvLayoutError, match="date, description and amount"):
        dataclasses.replace(SIGNED, description_column=2)
    with pytest.raises(CsvLayoutError, match="skip_rows"):
        dataclasses.replace(SIGNED, skip_rows=101)
    with pytest.raises(CsvLayoutError, match="date format"):
        dataclasses.replace(SIGNED, date_format="%s")
    with pytest.raises(CsvLayoutError, match="column must be from 0 to 63"):
        SignedAmount(64)


def test_layout_lists_the_columns_it_reads() -> None:
    assert SIGNED.columns == (0, 1, 2)
    assert DEBIT_CREDIT.columns == (3, 0, 1, 2)


def _draft(**overrides: Any) -> CsvLayoutDraft:
    values: dict[str, Any] = {
        field.name: getattr(SIGNED, field.name) for field in dataclasses.fields(CsvLayout)
    }
    values.update(overrides)
    return CsvLayoutDraft(**values)


def test_complete_draft_becomes_a_layout() -> None:
    assert _draft().to_layout() == SIGNED


@pytest.mark.parametrize(
    "missing", ["date_column", "description_column", "amount", "date_format", "invert_signs"]
)
def test_incomplete_draft_has_no_layout(missing: str) -> None:
    draft = _draft(**{missing: None})

    assert draft.to_layout() is None
    assert draft.to_dict()[missing] is None


def test_draft_validates_the_parts_it_has() -> None:
    with pytest.raises(CsvLayoutError, match="must all be different"):
        _draft(date_column=None, description_column=2)
    with pytest.raises(CsvLayoutError, match="date format"):
        _draft(date_format="%Q")
