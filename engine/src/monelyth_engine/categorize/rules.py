"""Tier 2: keyword and regex rules ("anything containing *uber eats* is Dining Out").

A rule is matched against two texts of a transaction: the cleaned merchant name and the bank's
raw description. Both match types ignore case:

- ``contains`` matches whole words, also ignoring accents and punctuation, so ``tim hortons``
  matches "TIM HORTONS #2231" and ``t&t supermarket`` matches "T&T SUPERMARKET", while ``bar``
  never matches "BARBER" and ``uber`` never matches "KUBER".
- ``regex`` is a Python regular expression searched in each text.

Rules are tried in the order :func:`~monelyth_engine.db.rules.list_rules` returns them, and the
first match answers. Regexes come from the user, and Python's ``re`` has no timeout, so
:func:`clean_pattern` refuses the shapes that make matching take exponential or high-polynomial
time (repeated groups that themselves repeat or branch, more than a few long repeats or
alternatives, back-references), and texts are cut to :data:`MAX_MATCH_TEXT_LENGTH` characters
before a regex sees them.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from monelyth_engine.categorize.models import CategorizationInput, Suggestion
from monelyth_engine.db.models import Category, CategorySource
from monelyth_engine.db.rules import Rule, RuleMatchType
from monelyth_engine.normalize import merchant_key

MAX_PATTERN_LENGTH: Final = 200
MAX_MATCH_TEXT_LENGTH: Final = 300
"""Bank descriptions are well under this; the cap bounds the cost of any one regex search."""
MAX_LONG_REPEATS: Final = 2
"""``*``, ``+``, ``{n,}`` (and ``{n,m}`` wider than :data:`MAX_NARROW_SPREAD`) allowed in one
regex."""
MAX_CHOICES: Final = 10
"""``|`` alternatives and optional parts (``?``, narrow ``{n,m}``) allowed in one regex."""
LONG_REPEAT_COST: Final = 7
MAX_COMPLEXITY: Final = 16
"""Budget for ``LONG_REPEAT_COST * long repeats + choices``.

On a hostile near-miss of :data:`MAX_MATCH_TEXT_LENGTH` characters, each long repeat that can
overlap another multiplies the work by about the text length (roughly 2**7 here) and each
choice roughly doubles it. Measured on a laptop, the worst patterns within this budget take
about 20 ms per text; one long repeat more takes seconds."""
MAX_NARROW_SPREAD: Final = 3
"""A ``{n,m}`` with m - n up to this counts as a choice, like ``?``; wider, as a long repeat."""

_WHITESPACE: Final = re.compile(r"\s+")
_COUNT: Final = re.compile(r"\{(?P<low>\d*)(?P<comma>,?)(?P<high>\d*)\}")

logger = logging.getLogger(__name__)


class RulePatternError(ValueError):
    """A rule's pattern can't be used. The message is shown to the user."""


def clean_pattern(pattern: str, match_type: RuleMatchType) -> str:
    """Check a pattern the user typed and return it in the form to store.

    Surrounding whitespace is removed; for ``contains``, runs of spaces become one.

    Raises:
        RulePatternError: if the pattern is empty, too long, can't match anything useful, or
            (for ``regex``) is invalid or could take too long to match.
    """
    text = pattern.strip()
    if match_type is RuleMatchType.CONTAINS:
        text = _WHITESPACE.sub(" ", text)
    if not text:
        raise RulePatternError("Enter the text the rule should look for.")
    if len(text) > MAX_PATTERN_LENGTH:
        raise RulePatternError(f"Keep the pattern to {MAX_PATTERN_LENGTH} characters or fewer.")
    if match_type is RuleMatchType.CONTAINS:
        if not merchant_key(text):
            raise RulePatternError("The text to look for needs at least one letter or digit.")
        return text

    _check_regex_shape(text)
    try:
        compiled = re.compile(text, re.IGNORECASE)
    except re.error as error:
        raise RulePatternError(f"That isn't a valid regular expression: {error.msg}.") from None
    if compiled.search("") is not None:
        raise RulePatternError(
            "That regular expression also matches empty text, so it would match every "
            "transaction. Make it require at least one character."
        )
    return text


@dataclass(frozen=True, slots=True)
class PatternMatcher:
    """A checked pattern, prepared for matching many transactions."""

    _words: str | None
    """For ``contains``: the pattern's merchant key padded with spaces."""
    _regex: re.Pattern[str] | None

    @classmethod
    def compile(cls, pattern: str, match_type: RuleMatchType) -> PatternMatcher:
        """Raises: RulePatternError: if the pattern can't be used (see :func:`clean_pattern`)."""
        cleaned = clean_pattern(pattern, match_type)
        if match_type is RuleMatchType.CONTAINS:
            return cls(f" {merchant_key(cleaned)} ", None)
        return cls(None, re.compile(cleaned, re.IGNORECASE))

    def matches(self, texts: MatchTexts) -> bool:
        if self._words is not None:
            return any(self._words in words for words in texts.words)
        if self._regex is None:  # pragma: no cover - compile() always sets one of the two
            raise AssertionError("A pattern matcher needs words or a regex")
        return any(self._regex.search(text) for text in texts.raw)


@dataclass(frozen=True, slots=True)
class MatchTexts:
    """A transaction's merchant name and description, prepared once for matching every rule."""

    raw: tuple[str, ...]
    """For regexes: each text cut to :data:`MAX_MATCH_TEXT_LENGTH` characters."""
    words: tuple[str, ...]
    """For ``contains``: each text's merchant key padded with spaces."""

    @classmethod
    def of(cls, merchant: str | None, description: str) -> MatchTexts:
        texts = (description,) if merchant is None else (merchant, description)
        return cls(
            raw=tuple(text[:MAX_MATCH_TEXT_LENGTH] for text in texts),
            words=tuple(f" {merchant_key(text)} " for text in texts),
        )


def prepare_rules(rules: Sequence[Rule]) -> list[tuple[Rule, PatternMatcher]]:
    """The usable rules with their matchers, in the order given (the order they are tried).

    A stored pattern is only unusable if the database was edited by hand; such a rule is
    logged and left out rather than stopping categorization."""
    prepared: list[tuple[Rule, PatternMatcher]] = []
    for rule in rules:
        try:
            prepared.append((rule, PatternMatcher.compile(rule.pattern, rule.match_type)))
        except RulePatternError as error:
            logger.warning("Skipping rule %d (%r): %s", rule.id, rule.pattern, error)
    return prepared


class RulesCategorizer:
    """Answers with the category of the first rule that matches, with full confidence."""

    def __init__(self, rules: Sequence[Rule]) -> None:
        self._rules = prepare_rules(rules)

    @property
    def source(self) -> CategorySource:
        return CategorySource.RULE

    def suggest(
        self, items: Sequence[CategorizationInput], categories: Sequence[Category]
    ) -> list[Suggestion | None]:
        del categories  # Rules name their category themselves.
        return [self._suggest(item) for item in items]

    def _suggest(self, item: CategorizationInput) -> Suggestion | None:
        texts = MatchTexts.of(item.merchant, item.description)
        for rule, matcher in self._rules:
            if matcher.matches(texts):
                return Suggestion(
                    category_id=rule.category_id,
                    source=CategorySource.RULE,
                    confidence=1.0,
                )
        return None


@dataclass(slots=True)
class _Group:
    repeats: bool = False
    """Something inside repeats (``*``, ``+``, ``{m,n}`` with n > 1)."""
    branches: bool = False
    """The group contains ``|``."""


@dataclass(frozen=True, slots=True)
class _Quantifier:
    end: int
    """Index just past it."""
    repeats: bool
    """Can match its atom more than once."""
    long_run: bool
    """Can match a run of any length (``*``, ``+``, ``{n,}``, or a wide ``{n,m}``)."""
    choice: bool
    """Matches its atom a few different numbers of times (``?``, a narrow ``{n,m}``)."""


_TOO_SLOW: Final = "That regular expression could take too long to check: "


def _check_regex_shape(pattern: str) -> None:
    """Refuse regexes whose matching time can explode on some text.

    Python's matcher backtracks: on a near-miss it tries every way the pattern could have
    matched. A repeated group that can match the same text in more than one way (``(a+)+``,
    ``(a|ab)*``) makes that exponential; several runs that can overlap (``.*.*.*``) make it a
    high power of the text length; and each alternative or optional part can double it. This
    walks the pattern once and enforces a budget for each, plus no back-references. Syntax
    errors it lets through are reported by ``re.compile`` afterwards.

    Raises:
        RulePatternError: naming the problem.
    """
    groups: list[_Group] = [_Group()]
    long_runs = 0
    choices = 0
    last_group: _Group | None = None
    """The group that just closed, if the previous token was ``)``."""
    can_repeat = False
    """Whether the previous token is something a quantifier may follow."""
    i = 0
    while i < len(pattern):
        char = pattern[i]
        closed = None
        if char == "\\":
            escaped = pattern[i + 1 : i + 2]
            if escaped.isdigit() and escaped != "0":
                raise _no_back_references()
            i += 2
            can_repeat = True
        elif char == "[":
            i = _skip_class(pattern, i)
            can_repeat = True
        elif char == "(":
            if pattern.startswith("(?P=", i):
                raise _no_back_references()
            if pattern.startswith("(?#", i):
                end = pattern.find(")", i)
                i = len(pattern) if end < 0 else end + 1
                last_group = None
                continue
            groups.append(_Group())
            i += 1
            can_repeat = False
        elif char == ")":
            if len(groups) > 1:
                closed = groups.pop()
                groups[-1].repeats |= closed.repeats
                groups[-1].branches |= closed.branches
            i += 1
            can_repeat = True
        elif char == "|":
            groups[-1].branches = True
            choices += 1
            i += 1
            can_repeat = False
        elif char in "*+?{" and can_repeat and (quantifier := _quantifier_at(pattern, i)):
            if (
                quantifier.repeats
                and last_group is not None
                and (last_group.repeats or last_group.branches)
            ):
                raise RulePatternError(
                    f"{_TOO_SLOW}it repeats a group that itself repeats or has alternatives, "
                    "like (a+)+ or (a|b)*. Rewrite it without the outer repeat, e.g. [ab]+ "
                    "instead of (a|b)+."
                )
            groups[-1].repeats |= quantifier.repeats
            long_runs += quantifier.long_run
            choices += quantifier.choice
            i = quantifier.end
            # A lazy or possessive marker belongs to this quantifier.
            if i < len(pattern) and pattern[i] in "?+":
                i += 1
            can_repeat = False
        else:
            # A literal (including a "{" that doesn't start a count), or a syntax error that
            # re.compile reports.
            i += 1
            can_repeat = True
        last_group = closed

    if (
        long_runs > MAX_LONG_REPEATS
        or choices > MAX_CHOICES
        or LONG_REPEAT_COST * long_runs + choices > MAX_COMPLEXITY
    ):
        raise RulePatternError(
            f"{_TOO_SLOW}it combines too many repeats (*, +, {{n,}}), alternatives (|) and "
            "optional parts (?). Simplify it, or split it into several rules."
        )


def _quantifier_at(pattern: str, i: int) -> _Quantifier | None:
    """The quantifier starting at ``i``, or ``None`` for a ``{`` that Python reads as a literal
    brace (one not followed by a well-formed count)."""
    char = pattern[i]
    if char == "?":
        return _Quantifier(i + 1, repeats=False, long_run=False, choice=True)
    if char in "*+":
        return _Quantifier(i + 1, repeats=True, long_run=True, choice=False)
    match = _COUNT.match(pattern, i)
    if match is None or not (match["low"] or match["high"]):
        return None
    low = int(match["low"] or 0)
    if not match["comma"]:
        return _Quantifier(match.end(), repeats=low > 1, long_run=False, choice=False)
    if not match["high"]:
        return _Quantifier(match.end(), repeats=True, long_run=True, choice=False)
    high = int(match["high"])
    spread = high - low
    return _Quantifier(
        match.end(),
        repeats=high > 1,
        long_run=spread > MAX_NARROW_SPREAD,
        choice=0 < spread <= MAX_NARROW_SPREAD,
    )


def _skip_class(pattern: str, start: int) -> int:
    """The index just past the character class opening at ``start``."""
    i = start + 1
    if pattern.startswith("^", i):
        i += 1
    if pattern.startswith("]", i):  # A leading "]" is a literal.
        i += 1
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 2
        elif pattern[i] == "]":
            return i + 1
        else:
            i += 1
    return i  # Unterminated; re.compile reports it.


def _no_back_references() -> RulePatternError:
    return RulePatternError("Back-references such as \\1 aren't supported in rules.")
