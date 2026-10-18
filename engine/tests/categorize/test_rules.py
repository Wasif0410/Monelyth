from __future__ import annotations

import logging
import re
import time

import pytest

from monelyth_engine.categorize.models import Suggestion
from monelyth_engine.categorize.rules import (
    MAX_MATCH_TEXT_LENGTH,
    MAX_PATTERN_LENGTH,
    MatchTexts,
    PatternMatcher,
    RulePatternError,
    RulesCategorizer,
    clean_pattern,
)
from monelyth_engine.db.models import CategorySource
from monelyth_engine.db.rules import RuleAuthor, RuleMatchType
from tests.categorize.conftest import item, rule

CONTAINS = RuleMatchType.CONTAINS
REGEX = RuleMatchType.REGEX


def _matches(pattern: str, text: str, match_type: RuleMatchType = CONTAINS) -> bool:
    return PatternMatcher.compile(pattern, match_type).matches(MatchTexts.of(None, text))


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        ("tim hortons", "TIM HORTONS #2231 TORONTO ON"),
        ("t&t supermarket", "POS PURCHASE T&T SUPERMARKET #021"),
        ("mcdonald's", "MCDONALDS 40213"),
        ("cafe", "LITTLE PIGEON CAFÉ"),
        ("apple com bill", "APPLE.COM/BILL 866-712-7753"),
        ("uber eats", "UBER* EATS PENDING"),
    ],
)
def test_contains_matches_whole_words_ignoring_case_accents_and_punctuation(
    pattern: str, text: str
) -> None:
    assert _matches(pattern, text)


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        ("bar", "QUEEN ST BARBER"),
        ("uber", "KUBER RESTAURANT"),
        ("gas", "LAS VEGAS STRIP"),
        ("uber eats", "UBER TRIP EATON CENTRE"),
    ],
)
def test_contains_never_matches_inside_a_word(pattern: str, text: str) -> None:
    assert not _matches(pattern, text)


def test_rules_match_the_merchant_name_or_the_description() -> None:
    matcher = PatternMatcher.compile("blue bottle", CONTAINS)

    assert matcher.matches(MatchTexts.of("Blue Bottle", "SQ *BB 0423"))
    assert matcher.matches(MatchTexts.of("BB Coffee", "SQ *BLUE BOTTLE 0423"))
    assert not matcher.matches(MatchTexts.of("Starbucks", "STARBUCKS 04312"))


def test_regex_is_case_insensitive_and_searches_anywhere() -> None:
    assert _matches(r"\bpayment\b.*\bvisa\b", "Online Payment - Demo Bank VISA", REGEX)
    assert _matches(r"^amzn mktp", "AMZN MKTP CA*FZ1WD", REGEX)
    assert not _matches(r"^mktp", "AMZN MKTP CA*FZ1WD", REGEX)


def test_regex_only_sees_the_start_of_very_long_texts() -> None:
    text = "x" * MAX_MATCH_TEXT_LENGTH + " NETFLIX"

    assert not _matches("netflix", text, REGEX)
    assert _matches("netflix", "x" * (MAX_MATCH_TEXT_LENGTH - 8) + " NETFLIX", REGEX)


def test_clean_pattern_trims_and_collapses_spaces_for_contains() -> None:
    assert clean_pattern("  uber   eats ", CONTAINS) == "uber eats"
    assert clean_pattern(r"  uber\s+eats ", REGEX) == r"uber\s+eats"
    assert clean_pattern("a  b", REGEX) == "a  b"


@pytest.mark.parametrize(
    ("pattern", "match_type", "message"),
    [
        ("   ", CONTAINS, "Enter the text"),
        ("", REGEX, "Enter the text"),
        ("x" * (MAX_PATTERN_LENGTH + 1), CONTAINS, f"{MAX_PATTERN_LENGTH} characters"),
        ("--- & ---", CONTAINS, "at least one letter or digit"),
        ("uber(eats", REGEX, "isn't a valid regular expression: missing )"),
        ("[a-", REGEX, "isn't a valid regular expression"),
        ("a*", REGEX, "matches empty text"),
        ("(?:inc)?", REGEX, "matches empty text"),
    ],
)
def test_clean_pattern_refuses_unusable_patterns(
    pattern: str, match_type: RuleMatchType, message: str
) -> None:
    with pytest.raises(RulePatternError, match=re.escape(message)):
        clean_pattern(pattern, match_type)


@pytest.mark.parametrize(
    "pattern",
    [
        r"(a+)+b",
        r"(\w+\s?)*x",
        r"(?:a|ab)*c",
        r"((ab)*c)+",
        r"(a|b){2,}",
        r"(x+){1,10}y",
        r"(?P<word>\d+)+!",
    ],
)
def test_clean_pattern_refuses_repeated_groups_that_repeat_or_branch(pattern: str) -> None:
    with pytest.raises(RulePatternError, match="could take too long"):
        clean_pattern(pattern, REGEX)


@pytest.mark.parametrize(
    "pattern",
    [
        r"a.*b.*c.*",
        r"a+b+c+",
        r"\d{1,20}.*\d+x+",
        "a?" * 11 + "b",
        "(a|b|c|d|e|f)(g|h|i|j|k|l|m)",
        "x{1,2}" * 11,
        r"a.*b.*c?d?e?",
        r"(?:sq|tst|sp|pp|ctb|paypal|amzn)\s*\*.*x?y?z?",
    ],
)
def test_clean_pattern_limits_repeats_alternatives_and_optional_parts(pattern: str) -> None:
    with pytest.raises(RulePatternError, match="combines too many"):
        clean_pattern(pattern, REGEX)


@pytest.mark.parametrize("pattern", [r"(a)\1", r"(?P<x>a)(?P=x)"])
def test_clean_pattern_refuses_back_references(pattern: str) -> None:
    with pytest.raises(RulePatternError, match="Back-references"):
        clean_pattern(pattern, REGEX)


@pytest.mark.parametrize(
    "pattern",
    [
        r"uber\s*eats",
        r"\bpayment\b.*\b(visa|mastercard|amex|credit card)\b",
        r"(inc|ltd)\.?$",
        r"^(?:sq|tst)\s*\*",
        r"\d{4}-\d{2}",
        r"x{2}y",
        r"a{,3}b",
        r"\d{3,5}-\d{3,6}",
        r"literal{brace}",
        r"[(+*]+x",
        r"[]a]+",
        r"(?i)netflix(?#streaming)",
        r"amzn.*?mktp",
        r"\(a+\)+",
        r"(\s+inc)?\s*corp",
    ],
)
def test_clean_pattern_accepts_ordinary_regexes(pattern: str) -> None:
    assert clean_pattern(pattern, REGEX) == pattern


def test_accepted_patterns_match_quickly_even_on_hostile_text() -> None:
    # The worst shape clean_pattern allows: two overlapping long repeats and two optional
    # parts, on a long near-miss.
    matcher = PatternMatcher.compile("a?a?a.*a.*z", REGEX)
    hostile = MatchTexts.of(None, "a" * 10_000)

    started = time.perf_counter()
    assert not matcher.matches(hostile)
    assert time.perf_counter() - started < 0.5


def test_first_matching_rule_answers_with_full_confidence() -> None:
    categorizer = RulesCategorizer(
        [rule("uber eats", 6, rule_id=1), rule("uber", 10, rule_id=2), rule("lyft", 10)]
    )

    answers = categorizer.suggest(
        [item("UBER* EATS"), item("UBER *TRIP"), item("SQ *BLUE BOTTLE")], []
    )

    assert answers == [
        Suggestion(category_id=6, source=CategorySource.RULE, confidence=1.0),
        Suggestion(category_id=10, source=CategorySource.RULE, confidence=1.0),
        None,
    ]
    assert categorizer.source is CategorySource.RULE


def test_a_rule_stored_with_an_unusable_pattern_is_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    categorizer = RulesCategorizer(
        [rule("(a+)+", 1, rule_id=7, match_type=REGEX, created_by=RuleAuthor.USER), rule("a", 2)]
    )

    assert categorizer.suggest([item("AAA A")], []) == [
        Suggestion(category_id=2, source=CategorySource.RULE, confidence=1.0)
    ]
    assert "Skipping rule 7" in caplog.text
