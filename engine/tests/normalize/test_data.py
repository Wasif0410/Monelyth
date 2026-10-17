"""Integrity checks for the hand-edited data tables, so a careless addition fails loudly."""

from __future__ import annotations

from collections import Counter

import pytest

from monelyth_engine.normalize import merchant_key, normalize_merchant
from monelyth_engine.normalize.aliases import ALIASES, UPPERCASE_WORDS
from monelyth_engine.normalize.locations import (
    CITIES,
    CITY_CONNECTORS,
    CODES_NEEDING_A_CITY,
    CODES_NEEDING_TWO_WORDS,
    COUNTRY_CODES,
    REGION_CODES,
)


def test_alias_keys_are_sorted() -> None:
    assert list(ALIASES) == sorted(ALIASES)


def test_alias_keys_are_lowercase_and_trimmed() -> None:
    assert all(alias == alias.lower().strip() for alias in ALIASES)


def test_no_two_aliases_share_a_key() -> None:
    counts = Counter(merchant_key(alias) for alias in ALIASES)

    assert [key for key, count in counts.items() if count > 1] == []


def test_no_canonical_name_is_claimed_by_a_different_alias() -> None:
    for canonical in set(ALIASES.values()):
        claimed = {
            target
            for alias, target in ALIASES.items()
            if merchant_key(alias) == merchant_key(canonical)
        }
        assert claimed <= {canonical}, canonical


@pytest.mark.parametrize("canonical", sorted(set(ALIASES.values())))
def test_canonical_names_clean_to_themselves(canonical: str) -> None:
    assert normalize_merchant(canonical) == canonical


@pytest.mark.parametrize("alias", sorted(ALIASES))
def test_every_alias_resolves(alias: str) -> None:
    assert normalize_merchant(alias) == ALIASES[alias]


def test_alias_table_size() -> None:
    assert 40 <= len(ALIASES) <= 80


def test_location_entries_are_written_as_keys() -> None:
    entries = CITIES | REGION_CODES | COUNTRY_CODES | CITY_CONNECTORS

    assert sorted(entry for entry in entries if merchant_key(entry) != entry) == []


def test_uppercase_words_are_written_in_lowercase() -> None:
    assert all(word == word.lower() and " " not in word for word in UPPERCASE_WORDS)


def test_location_code_tiers_are_known_codes() -> None:
    assert CODES_NEEDING_A_CITY <= REGION_CODES | COUNTRY_CODES
    assert CODES_NEEDING_TWO_WORDS <= REGION_CODES | COUNTRY_CODES
    assert not CODES_NEEDING_A_CITY & CODES_NEEDING_TWO_WORDS
