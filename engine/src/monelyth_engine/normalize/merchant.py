"""Turn a bank's transaction description into a clean, stable merchant name.

Card networks pad the merchant's name with processor codes, store numbers, reference codes,
phone numbers and locations, and the padding changes from one purchase to the next even when
the merchant does not. The cleaned name is stored in ``transactions.merchant`` and keys merchant
memory, the categorizer's first tier, so every variant of one merchant must clean to the same
name. When a rule has to choose, it chooses consistency over prettiness.

Cleaning works on lowercase text and repeats these stages until nothing changes:

1. strip processor and channel prefixes (``SQ *``, ``VISA DEBIT PUR``), nested or not;
2. strip noise: card, store, terminal, reference and phone numbers, dates and postal codes;
3. strip a trailing location (``TORONTO ON``, ``SAN FRANCISCO CA``, ``USA``);
4. reduce websites to their name (``HELP.UBER.COM`` becomes ``uber``).

The alias table is checked before every stage, so an alias can match a description at whatever
point it becomes recognisable. Without an alias, the result is title-cased for display.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from typing import Final

from monelyth_engine.normalize.aliases import ALIASES, UPPERCASE_WORDS
from monelyth_engine.normalize.locations import (
    CITIES,
    CITY_CONNECTORS,
    CODES_NEEDING_A_CITY,
    CODES_NEEDING_TWO_WORDS,
    COUNTRY_CODES,
    REGION_CODES,
)

_WHITESPACE: Final = re.compile(r"\s+")
_ALPHANUMERIC: Final = re.compile(r"[^\W_]")

# Typographic apostrophes (curly quotes and the like), so names written with them clean and
# key like names written with a plain apostrophe.
_APOSTROPHE_CHARS: Final = "\u2018\u2019\u02bc`\u00b4"
_TO_ASCII_APOSTROPHE: Final = str.maketrans(dict.fromkeys(_APOSTROPHE_CHARS, "'"))

# --- Stage 1: prefixes -------------------------------------------------------------------------

_PROCESSOR_CODES: Final = (
    *("cko", "dd", "doordash", "fs", "ic", "in", "paypal", "pp", "py", "sp", "sq", "squ"),
    *("sumup", "tst", "wpy", "zettle"),
)
"""Payment processors and platforms that write ``CODE*MERCHANT``: Square, Toast, PayPal,
Shopify, DoorDash, Checkout.com, Instacart, Intuit, FastSpring, WePay, SumUp, Zettle and others.
The ``*`` is required, so a merchant whose name merely starts with these letters is safe."""

_CHANNEL_PREFIXES: Final = (
    r"checkcard(?: \d{4})?",
    r"contactless",
    r"dd ?\*? ?doordash",
    r"debit (?:card )?purchase",
    r"interac (?:retail )?purchase",
    r"pos(?: purchase| debit)?",
    r"pre-?authori[sz]ed debit",
    r"purchase authori[sz]ed on(?: \d{1,2}/\d{1,2}(?:/\d{2,4})?)?",
    r"recurring payment",
    r"sp",
    r"visa debit (?:retail )?(?:purchase|pur)",
)
"""How the payment was made rather than who was paid. Each must be followed by a space."""

# Requiring something after the prefix means a description that is nothing but a prefix
# ("CONTACTLESS") is kept rather than cleaned away.
_PREFIX: Final = re.compile(
    rf"(?:(?:{'|'.join(_CHANNEL_PREFIXES)})(?= )|(?:{'|'.join(_PROCESSOR_CODES)})[ _]?\*)"
    r"[\s*:#-]*(?=\S)"
)

# --- Stage 2: noise ----------------------------------------------------------------------------

_PHONE: Final = re.compile(
    r"(?<![\w-])(?:\+?1[ .-]?)?(?:\(\d{3}\) ?|\d{3}[ .-]?)\d{3}[ .-]?\d{4}(?![\w-])"
)
_DATE_OR_TIME: Final = re.compile(
    r"(?<![\w/:-])"
    r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{1,2}:\d{2}(?::\d{2})?(?: ?[ap]m)?)"
    r"(?![\w/:-])"
)
_MASKED_CARD: Final = re.compile(r"(?<![\w*])[x*]{2,}(?:[ -]?[x*]{4})*[ -]?\d{2,4}(?!\w)")
_POSTAL_CODE: Final = re.compile(r"(?<!\S)[abceghj-nprstvxy]\d[a-z] ?\d[a-z]\d(?!\S)")
_CARD_NUMBER: Final = re.compile(r"(?<!\S)card(?: ending(?: in)?| no\.?)?[ #]*\d{4}(?!\S)")
_LABELLED_NUMBER: Final = re.compile(
    r"(?<!\S)"
    r"(?:auth|branch|conf|inv|invoice|loc|location|order|ref|reference|term|terminal|trans|txn)"
    r"\.?(?: ?(?:#|no\.?))? ?[a-z]*\d[\w-]*(?!\S)"
)
"""A number with a label that is never part of a name: ``TERMINAL #T12``, ``REF 88123``. The
label ``STORE`` is left out on purpose because names end in it (``THE BEER STORE #1234``); the
number after it is removed like any other store number."""
_STAR_CODE: Final = re.compile(r"\* ?[a-z\d]*\d[a-z\d]*(?!\S)")
"""A reference code after a ``*``, as in ``AMZN MKTP CA*2K4X91``. ``UBER *TRIP`` has no digit
and is kept."""
_PUNCTUATION: Final = re.compile(r"[^\w\s&'+./#-]|_")
"""Everything except the punctuation that can be part of a name or a website."""

_NOISE_PATTERNS: Final = (
    _PHONE,
    _DATE_OR_TIME,
    _MASKED_CARD,
    _POSTAL_CODE,
    _CARD_NUMBER,
    _LABELLED_NUMBER,
    _STAR_CODE,
    _PUNCTUATION,
)

_NOISE_WORD: Final = re.compile(r"#(?:\S*\d\S*)?|0\d+|\d{3,}|[a-z]{1,2}\d{3,}|[^\w&]+")
"""A whole word that is never part of a name: ``#1234``, ``0423``, ``12345``, store codes such as
``W123``, and stray punctuation. One- and two-digit numbers are kept (``4 PAWS``, ``FOREVER 21``)
and so is a lone ``&`` between words."""
_REFERENCE_CODE_SHAPE: Final = re.compile(r"(?=[a-z\d]*\d)(?=[a-z\d]*[a-z])[a-z\d]{5,}")
_ALTERNATING: Final = re.compile(r"[a-z]\d+[a-z]|\d[a-z]+\d")

# --- Stage 3: locations ------------------------------------------------------------------------

_MAX_CITY_WORDS: Final = max(len(city.split()) for city in CITIES)

# --- Stage 4: websites -------------------------------------------------------------------------

_URL: Final = re.compile(r"(?:https?://)?(?P<host>[a-z\d-]+(?:\.[a-z\d-]+)+)(?:/\S*)?")
_TOP_LEVEL_DOMAINS: Final = frozenset(
    {
        *("ai", "app", "au", "biz", "ca", "co", "com", "de", "eu", "fm", "fr", "gg", "ie", "info"),
        *("io", "jp", "ly", "me", "net", "nz", "online", "org", "shop", "store", "tv", "uk", "us"),
    }
)

# --- Display -----------------------------------------------------------------------------------

_MINOR_WORDS: Final = frozenset({"a", "an", "and", "at", "by", "for", "of", "the", "to"})
"""Lowercase inside a name, as in "Bank of Montreal", but capitalized first and last. "In" and
"on" are left out because in names they are usually part of a phrase ("Game On Sports Bar")."""
_WORD_START: Final = re.compile(r"(?:^|(?<=[-/.&+(]))[^\W\d_]")
_ELIDED_ARTICLE: Final = re.compile(r"[^\W\d_]'(?!s$)[^\W\d_]")
"""``o'reilly`` and ``d'angelo`` capitalize after the apostrophe; ``joe's`` and ``j's`` don't."""

# --- Keys --------------------------------------------------------------------------------------

_KEY_APOSTROPHES: Final = re.compile(f"['{_APOSTROPHE_CHARS}]")
_KEY_SEPARATORS: Final = re.compile(r"[\W_]+")

_MAX_PASSES: Final = 8
"""Every stage that changes the text deletes at least one non-space character, so cleaning always
settles, usually within two or three passes. The cap only guards against a future rule that
breaks that."""


def normalize_merchant(description: str) -> str:
    """Return the display name for a transaction description.

    ``SQ *BLUE BOTTLE 0423 TORONTO ON`` becomes ``Blue Bottle``. The result is never empty: when
    cleaning would remove everything, the description is returned with its whitespace collapsed.
    Applying the function to its own output returns that output unchanged.

    Raises:
        ValueError: if ``description`` is empty or only whitespace.
    """
    original = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", description)).strip()
    if not original:
        raise ValueError("description must not be blank")

    text = original.translate(_TO_ASCII_APOSTROPHE).lower()
    for _ in range(_MAX_PASSES):
        start = text
        for stage in _STAGES:
            alias = _ALIAS_LOOKUP.get(merchant_key(text))
            if alias is not None:
                return alias
            text = stage(text)
        if text == start:
            break

    if not _ALPHANUMERIC.search(text):
        return original
    # Normally the last pass already checked this text; this covers stopping at the pass cap.
    return _ALIAS_LOOKUP.get(merchant_key(text)) or _display_case(text)


def merchant_key(name: str) -> str:
    """Return the key merchant memory looks ``name`` up by.

    Case, accents, apostrophes and other punctuation are ignored and spacing is collapsed, so
    "Blue Bottle", "BLUE  BOTTLE" and "blue-bottle" share the key ``blue bottle``. A name with no
    letters or digits has the empty key.
    """
    text = name.casefold()
    if not text.isascii():
        decomposed = unicodedata.normalize("NFKD", text)
        text = "".join(char for char in decomposed if not unicodedata.combining(char))
    text = _KEY_APOSTROPHES.sub("", text)
    return _KEY_SEPARATORS.sub(" ", text).strip()


def _strip_prefixes(text: str) -> str:
    while match := _PREFIX.match(text):
        text = text[match.end() :]
    return text


def _strip_noise(text: str) -> str:
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    words = [
        word
        for word in text.split()
        if not _NOISE_WORD.fullmatch(word) and not _is_reference_code(word)
    ]
    # Drop a dangling "&" left behind when the words on one side of it were noise.
    while words and not _ALPHANUMERIC.search(words[0]):
        words.pop(0)
    while words and not _ALPHANUMERIC.search(words[-1]):
        words.pop()
    return " ".join(words)


def _is_reference_code(word: str) -> bool:
    """Whether ``word`` is a long mix of letters and digits, like ``2K4X91`` or ``S5862578624``.

    Requiring three digits, or letters and digits that alternate, keeps brand names that merely
    contain a digit, such as ``7ELEVEN`` and ``1PASSWORD``.
    """
    if not _REFERENCE_CODE_SHAPE.fullmatch(word):
        return False
    digits = sum(char.isdigit() for char in word)
    return digits >= 3 or _ALTERNATING.search(word) is not None


def _strip_location(text: str) -> str:
    """Strip a trailing ``[city] region``, ``region country`` or ``country`` from the name.

    A city is only recognised from the ``CITIES`` list, never guessed, so the real word in front
    of a two-letter word is never eaten: ``GAME ON`` keeps both words.
    """
    words = text.split()
    if len(words) >= 3 and words[-1] in COUNTRY_CODES and words[-2] in REGION_CODES:
        words.pop()
    if len(words) < 2:
        return " ".join(words)

    code = words[-1]
    name = words[:-1]
    if code in REGION_CODES:
        city_words = _trailing_city_words(name)
        if city_words:
            before_city = name[:-city_words]
            if before_city and before_city[-1] not in CITY_CONNECTORS:
                return " ".join(before_city)
            return " ".join(name)
    elif code not in COUNTRY_CODES:
        return " ".join(words)

    if _domain_name(name[-1]) is not None:
        return " ".join(name)
    if code in CODES_NEEDING_A_CITY:
        return " ".join(words)
    min_name_words = 2 if code in CODES_NEEDING_TWO_WORDS else 1
    return " ".join(name if len(name) >= min_name_words else words)


def _trailing_city_words(words: list[str]) -> int:
    """Return how many of the last ``words`` name a known city, or 0 if they don't."""
    for size in range(min(_MAX_CITY_WORDS, len(words)), 0, -1):
        if merchant_key(" ".join(words[-size:])) in CITIES:
            return size
    return 0


def _reduce_websites(text: str) -> str:
    """Replace a leading website with its name and drop websites later in the text.

    A website at the start is the merchant (``NETFLIX.COM``); one further along is a support
    address (``UBER *TRIP HELP.UBER.COM``) that repeats or adds nothing to the name before it.
    """
    words = text.split()
    if not words:
        return text
    first = _domain_name(words[0])
    rest = [word for word in words[1:] if _domain_name(word) is None]
    return " ".join([words[0] if first is None else first, *rest])


def _domain_name(word: str) -> str | None:
    """Return the name in a web address (``uber`` for ``help.uber.com``), or None for a word."""
    match = _URL.fullmatch(word)
    if match is None:
        return None
    labels = match.group("host").split(".")
    if labels[-1] not in _TOP_LEVEL_DOMAINS:
        return None
    while len(labels) > 1 and labels[-1] in _TOP_LEVEL_DOMAINS:
        labels.pop()
    return labels[-1]


def _display_case(text: str) -> str:
    words = text.split()
    last = len(words) - 1
    return " ".join(
        _display_word(word, is_edge=index in (0, last)) for index, word in enumerate(words)
    )


def _display_word(word: str, *, is_edge: bool) -> str:
    if "/" in word:
        # Each side of "GST/HST" or "Food/Drink" is cased on its own.
        return "/".join(_display_word(part, is_edge=is_edge) for part in word.split("/"))
    if word in UPPERCASE_WORDS:
        return word.upper()
    if word in _MINOR_WORDS and not is_edge:
        return word
    word = _WORD_START.sub(lambda match: _capitalize(match.group()), word)
    if _ELIDED_ARTICLE.match(word):
        word = word[:2] + _capitalize(word[2]) + word[3:]
    return word


def _capitalize(letter: str) -> str:
    """Uppercase ``letter`` unless lowercasing wouldn't give it back (German sharp s becomes
    ``SS``), which would make cleaning the output a second time give a different name."""
    upper = letter.upper()
    return upper if upper.lower() == letter else letter


def _build_alias_lookup(aliases: Mapping[str, str]) -> dict[str, str]:
    lookup = {merchant_key(alias): canonical for alias, canonical in aliases.items()}
    for canonical in aliases.values():
        lookup.setdefault(merchant_key(canonical), canonical)
    return lookup


_STAGES: Final[tuple[Callable[[str], str], ...]] = (
    _strip_prefixes,
    _strip_noise,
    _strip_location,
    _reduce_websites,
)
_ALIAS_LOOKUP: Final = _build_alias_lookup(ALIASES)
