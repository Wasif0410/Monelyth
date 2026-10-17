from __future__ import annotations

import pytest

from monelyth_engine.normalize import merchant_key, normalize_merchant


@pytest.mark.parametrize(
    ("names", "key"),
    [
        (["Blue Bottle", "BLUE BOTTLE", "blue  bottle", " Blue-Bottle "], "blue bottle"),
        (["McDonald's", "MCDONALDS", "McDonald\u2019s", "mcdonald`s"], "mcdonalds"),
        (["H&M", "H & M", "h-m"], "h m"),
        (["Petro-Canada", "PETRO CANADA", "petro.canada"], "petro canada"),
        (["Caf\u00e9 Ol\u00e9", "CAFE OLE", "Cafe\u0301 Ole\u0301"], "cafe ole"),
        (["Stra\u00dfe", "STRASSE"], "strasse"),
        (["7-Eleven", "7 ELEVEN"], "7 eleven"),
    ],
)
def test_equivalent_names_share_a_key(names: list[str], key: str) -> None:
    assert {merchant_key(name) for name in names} == {key}


@pytest.mark.parametrize(
    ("first", "second"),
    [("Uber", "Uber Eats"), ("Costco", "Costco Gas"), ("Amazon", "Amazon Prime")],
)
def test_different_merchants_keep_different_keys(first: str, second: str) -> None:
    assert merchant_key(first) != merchant_key(second)


@pytest.mark.parametrize("name", ["Blue Bottle", "Trader Joe's", "\u0130stanbul Kebab", "H&M"])
def test_key_is_stable_on_its_own_output(name: str) -> None:
    key = merchant_key(name)

    assert merchant_key(key) == key


@pytest.mark.parametrize("name", ["", "   ", "&", "--"])
def test_name_without_letters_or_digits_has_empty_key(name: str) -> None:
    assert merchant_key(name) == ""


def test_raw_variants_share_a_key_after_normalizing() -> None:
    raws = ["SQ *BLUE BOTTLE 0423 TORONTO ON", "BLUE BOTTLE #00123", "blue bottle"]

    assert {merchant_key(normalize_merchant(raw)) for raw in raws} == {"blue bottle"}
