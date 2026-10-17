from __future__ import annotations

import sqlite3

import pytest

from monelyth_engine.db.csv_profiles import get_csv_profile, save_csv_profile

SIGNATURE = "3f1c9a"


def test_unknown_header_has_no_profile(db: sqlite3.Connection) -> None:
    assert get_csv_profile(db, SIGNATURE) is None


def test_profile_round_trips_exactly(db: sqlite3.Connection) -> None:
    mapping = '{"date": 0, "description": 1, "amount": 3}'

    save_csv_profile(db, SIGNATURE, mapping)

    assert get_csv_profile(db, SIGNATURE) == mapping


def test_saving_again_replaces_the_profile(db: sqlite3.Connection) -> None:
    save_csv_profile(db, SIGNATURE, '{"date": 0}')
    save_csv_profile(db, SIGNATURE, '{"date": 2}')
    save_csv_profile(db, "other", '{"date": 5}')

    assert get_csv_profile(db, SIGNATURE) == '{"date": 2}'
    assert get_csv_profile(db, "other") == '{"date": 5}'


@pytest.mark.parametrize(
    ("signature", "mapping", "message"),
    [
        ("", "{}", "header_signature"),
        (SIGNATURE, "{not json", "not valid JSON"),
        (SIGNATURE, "[0, 1]", "JSON object"),
    ],
)
def test_invalid_profiles_are_rejected(
    db: sqlite3.Connection, signature: str, mapping: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        save_csv_profile(db, signature, mapping)
    assert get_csv_profile(db, SIGNATURE) is None
