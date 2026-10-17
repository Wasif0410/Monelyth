"""Read single CSV cells: dates, amounts and descriptions.

Every function here works on one cell and has no other state, so the same rules serve both
detection (which tries them on every row to choose a layout) and parsing.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

DecimalSeparator = Literal[".", ","]

DECIMAL_SEPARATORS: Final[tuple[DecimalSeparator, ...]] = (".", ",")

DATE_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m/%d/%y",
    "%d/%m/%y",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%b %d, %Y",
)
"""Every date format a layout may use, in the order detection prefers them.

The codes look like ``strftime`` codes but are matched by this module, not by ``strptime``:
``strptime`` reads month names in the process locale, and an import must give the same result
on every machine. ``%b`` accepts English month names, abbreviated or in full.
"""

_MAX_CELL_LENGTH: Final = 64
"""Longest date or amount cell worth reading; anything longer is not a date or an amount."""
_MAX_INTEGER_DIGITS: Final = 13
"""Amounts up to just under 10 trillion. Keeps cents far inside SQLite's 64-bit integers."""
_TWO_DIGIT_YEAR_PIVOT: Final = 69
"""``%y`` maps 00-68 to 2000-2068 and 69-99 to 1969-1999, the same rule as POSIX ``strptime``."""

_MONTHS: Final = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}

_DATE_TOKENS: Final = {
    "%Y": (r"(?P<year>\d{4})", "YYYY"),
    "%y": (r"(?P<short_year>\d{2})", "YY"),
    "%m": (r"(?P<month>\d{1,2})", "MM"),
    "%d": (r"(?P<day>\d{1,2})", "DD"),
    "%b": (r"(?P<month_name>[A-Za-z]{3,9})\.?", "Mon"),
}
# Some banks append a time to the date ("2026-09-01 00:00:00", "09/01/2026 12:00 AM"). The
# time is dropped: a transaction's date is the day it posted.
_TIME_SUFFIX: Final = r"(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:\s*[AaPp][Mm])?)?"

_BLANK_CELLS: Final = frozenset({"", "-", "\u2013", "\u2014"})
"""Cells that mean "no value": empty, or a hyphen, en dash or em dash, which some banks put in
the unused debit or credit column."""
# Spaces used as thousands separators ("1 234,56"), and the Unicode minus sign.
_CHARACTER_FIXES: Final = str.maketrans(
    {"\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u2212": "-"}
)
_CURRENCY: Final = (
    r"(?:[$€£¥₹]|(?:C|CA|US|A|NZ|HK|S)\$"
    r"|CAD|USD|EUR|GBP|AUD|NZD|CHF|JPY|INR|MXN|HKD|SGD)"
)
_AMOUNT_PATTERN: Final = re.compile(
    rf"""
    (?P<leading_sign>[-+])?\s*
    (?:(?P<leading_currency>{_CURRENCY})\s*)?
    (?P<inner_sign>[-+])?\s*
    (?P<number>\d(?:[\d.,' ]*\d)?|[.,]\d+)
    \s*(?P<trailing_currency>{_CURRENCY})?
    \s*(?P<trailing_sign>-)?
    """,
    re.VERBOSE | re.IGNORECASE | re.ASCII,
)
_MARKER_PATTERN: Final = re.compile(r"(?<![A-Za-z])(?P<marker>CR|DR)\.?\s*$", re.IGNORECASE)
"""``CR`` (credit, money in) or ``DR`` (debit, money out) after the number: ``12.99 DR``."""
_DIGITS: Final = re.compile(r"\d+", re.ASCII)
_GROUP_SEPARATORS: Final = {".": ",' ", ",": ".' "}


class CsvValueError(ValueError):
    """A cell can't be read. The message completes the sentence "Row 14: ..." for the user."""


@dataclass(frozen=True, slots=True)
class _DateFormat:
    pattern: re.Pattern[str]
    label: str


def _compile_date_format(code: str) -> _DateFormat:
    pattern: list[str] = []
    label: list[str] = []
    index = 0
    while index < len(code):
        if code[index] == "%":
            regex, token_label = _DATE_TOKENS[code[index : index + 2]]
            pattern.append(regex)
            label.append(token_label)
            index += 2
            continue
        character = code[index]
        pattern.append(r"\s+" if character == " " else re.escape(character))
        label.append(character)
        index += 1
    return _DateFormat(re.compile("".join(pattern) + _TIME_SUFFIX, re.ASCII), "".join(label))


_COMPILED_DATE_FORMATS: Final = {code: _compile_date_format(code) for code in DATE_FORMATS}


def date_format_label(code: str) -> str:
    """How a date format is shown to people, e.g. ``"DD/MM/YYYY"`` for ``"%d/%m/%Y"``."""
    return _COMPILED_DATE_FORMATS[code].label


def match_date(text: str, code: str) -> datetime.date | None:
    """Read ``text`` as a date in format ``code``, or return ``None`` if it isn't one."""
    text = text.strip()
    if len(text) > _MAX_CELL_LENGTH:
        return None
    match = _COMPILED_DATE_FORMATS[code].pattern.fullmatch(text)
    if match is None:
        return None
    groups = match.groupdict()

    if (year_text := groups.get("year")) is not None:
        year = int(year_text)
    else:
        short_year = int(groups["short_year"])
        year = short_year + (2000 if short_year < _TWO_DIGIT_YEAR_PIVOT else 1900)

    if (month_name := groups.get("month_name")) is not None:
        month = _MONTHS.get(month_name.lower())
        if month is None:
            return None
    else:
        month = int(groups["month"])

    try:
        return datetime.date(year, month, int(groups["day"]))
    except ValueError:
        return None


def parse_date(text: str, code: str) -> datetime.date:
    """Like :func:`match_date`, but raise :class:`CsvValueError` when ``text`` isn't a date."""
    date = match_date(text, code)
    if date is None:
        raise CsvValueError(
            f"the date {quote(text)} doesn't match the format {date_format_label(code)}"
        )
    return date


def is_blank(text: str) -> bool:
    """Whether a cell holds no value: empty, only spaces, or a lone dash."""
    return text.strip() in _BLANK_CELLS


def has_credit_debit_marker(text: str) -> bool:
    """Whether an amount says its own direction with a ``CR`` or ``DR`` suffix."""
    return _MARKER_PATTERN.search(text) is not None


def parse_amount(text: str, decimal_separator: DecimalSeparator) -> int | None:
    """Read an amount cell as a signed number of cents, or ``None`` if the cell is blank.

    Accepts thousands separators, currency symbols and codes, and every common way of writing
    a negative number: ``-12.99``, ``12.99-``, ``(12.99)`` and ``12.99 DR``. ``12.99 CR`` is
    positive. The value goes through :class:`~decimal.Decimal`, never ``float``, so it is exact.

    Raises:
        CsvValueError: if the cell isn't a number, has more than one sign, has a fraction of a
            cent, or is implausibly large.
    """
    if is_blank(text):
        return None
    cleaned = text.translate(_CHARACTER_FIXES).strip()
    if len(cleaned) > _MAX_CELL_LENGTH:
        raise CsvValueError(f"the amount {quote(text)} isn't a number")

    # One entry per sign written in the cell; True means negative.
    signs: list[bool] = []
    if (marker := _MARKER_PATTERN.search(cleaned)) is not None:
        signs.append(marker["marker"].upper() == "DR")
        cleaned = cleaned[: marker.start()].rstrip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        signs.append(True)
        cleaned = cleaned[1:-1].strip()

    match = _AMOUNT_PATTERN.fullmatch(cleaned)
    if match is None or (match["leading_currency"] and match["trailing_currency"]):
        raise CsvValueError(f"the amount {quote(text)} isn't a number")
    signs.extend(
        sign == "-"
        for sign in (match["leading_sign"], match["inner_sign"], match["trailing_sign"])
        if sign
    )
    if len(signs) > 1:
        raise CsvValueError(f"the amount {quote(text)} has more than one sign")

    number = _plain_number(match["number"], decimal_separator)
    if number is None:
        raise CsvValueError(f"the amount {quote(text)} isn't a number")
    integer_part = number.partition(".")[0]
    if len(integer_part.lstrip("0")) > _MAX_INTEGER_DIGITS:
        raise CsvValueError(f"the amount {quote(text)} is too large")

    cents = Decimal(number) * 100
    if cents != cents.to_integral_value():
        raise CsvValueError(f"the amount {quote(text)} has a fraction of a cent")
    return -int(cents) if signs and signs[0] else int(cents)


def _plain_number(number: str, decimal_separator: DecimalSeparator) -> str | None:
    """Rewrite ``"1,234.56"`` (or ``"1.234,56"`` with a decimal comma) as ``"1234.56"``.

    Returns ``None`` when the separators don't form a valid number, e.g. ``"1,23.4"`` or a
    decimal comma in a file that uses decimal points.
    """
    integer_part, separator, fraction = number.partition(decimal_separator)
    if separator and not _DIGITS.fullmatch(fraction):
        return None

    group_separators = [
        char for char in _GROUP_SEPARATORS[decimal_separator] if char in integer_part
    ]
    if len(group_separators) > 1:
        return None
    if group_separators:
        groups = integer_part.split(group_separators[0])
        valid_groups = 1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])
        if not valid_groups or not all(_DIGITS.fullmatch(group) for group in groups):
            return None
        integer_part = "".join(groups)
    elif integer_part and not _DIGITS.fullmatch(integer_part):
        return None

    return f"{integer_part or '0'}.{fraction or '0'}"


def clean_description(text: str) -> str:
    """Remove outer whitespace and turn every run of inner whitespace into one space."""
    return " ".join(text.split())


def quote(text: str, limit: int = 40) -> str:
    """Show a cell's text inside a user-facing message, shortened if it is long."""
    text = clean_description(text)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f'"{text}"'
