"""The demo generator and statement files in :mod:`monelyth_engine.demo`.

``tests/test_sample_data.py`` checks the patterns inside the data, through the script.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Final

import pytest

from monelyth_engine.demo import SAMPLE_END_MONTH, Month, generate, sample_files
from monelyth_engine.demo.statements import (
    CARD_CSV,
    CARD_CSV_LAYOUT,
    CHECKING_CSV,
    CHECKING_CSV_LAYOUT,
    card_csv,
    checking_csv,
)
from monelyth_engine.ingest.csv_statement import detect_csv, parse_csv

COMMITTED_DIR: Final = Path(__file__).resolve().parents[3] / "sample-data"


def test_package_output_equals_the_committed_files() -> None:
    files = sample_files(generate(SAMPLE_END_MONTH))

    assert list(files) == [
        "demo-checking.csv",
        "demo-credit-card.csv",
        "demo-checking.ofx",
        "labels.csv",
    ]
    for name, text in files.items():
        assert text.encode() == (COMMITTED_DIR / name).read_bytes(), name


def test_generation_is_deterministic_for_any_month() -> None:
    month = Month(2026, 10)

    assert sample_files(generate(month)) == sample_files(generate(month))


def test_another_month_gives_other_statements() -> None:
    committed = sample_files(generate(SAMPLE_END_MONTH))
    later = sample_files(generate(Month(2026, 10)))

    for name in committed:
        assert later[name] != committed[name], name


def test_month_of_a_date() -> None:
    assert Month.of(datetime.date(2026, 2, 28)) == Month(2026, 2)
    assert Month(2026, 1).shifted(-1) == Month(2025, 12)


def test_through_keeps_only_rows_posted_by_that_day() -> None:
    full = generate(Month(2026, 10))
    cut_off = datetime.date(2026, 10, 17)

    dataset = full.through(cut_off)

    assert dataset.start == full.start
    assert dataset.end == cut_off
    assert dataset.checking == [row for row in full.checking if row.posted <= cut_off]
    assert dataset.card == [row for row in full.card if row.posted <= cut_off]
    assert len(dataset.checking) < len(full.checking)
    assert len(dataset.card) < len(full.card)


def test_through_the_last_day_or_later_keeps_everything() -> None:
    full = generate(Month(2026, 10))

    assert full.through(full.end) is full
    assert full.through(full.end + datetime.timedelta(days=30)) is full


def test_through_a_day_before_the_data_is_refused() -> None:
    full = generate(Month(2026, 10))

    with pytest.raises(ValueError, match="before the data starts"):
        full.through(full.start - datetime.timedelta(days=1))


@pytest.mark.parametrize(
    ("name", "layout"), [(CHECKING_CSV, CHECKING_CSV_LAYOUT), (CARD_CSV, CARD_CSV_LAYOUT)]
)
def test_layouts_are_what_detection_finds(name: str, layout: object) -> None:
    """The demo saves the same layout a user importing the sample file would confirm."""
    detection = detect_csv((COMMITTED_DIR / name).read_bytes())

    assert detection.questions == ()
    assert detection.layout.to_layout() == layout


def test_layouts_read_every_row() -> None:
    dataset = generate(Month(2026, 10))

    checking = parse_csv(checking_csv(dataset).encode(), CHECKING_CSV_LAYOUT)
    card = parse_csv(card_csv(dataset).encode(), CARD_CSV_LAYOUT)

    assert [(tx.posted_date, tx.description, tx.amount_cents) for tx in checking.transactions] == [
        (row.posted, row.description, row.amount_cents) for row in dataset.checking
    ]
    assert [(tx.posted_date, tx.description, tx.amount_cents) for tx in card.transactions] == [
        (row.posted, row.description, row.amount_cents) for row in dataset.card
    ]
