"""Types shared by every statement parser and by the code that stores their output.

Conventions used everywhere in Monelyth:

- Money is an ``int`` number of cents. Never use ``float`` for money.
- Sign: negative = money out of the account, positive = money in, for every account type.
  Parsers flip credit-card statements that show purchases as positive.
- Dates are ``datetime.date`` (the posting date; no time or timezone).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import StrEnum


class StatementFormat(StrEnum):
    CSV = "csv"
    OFX = "ofx"


@dataclass(frozen=True, slots=True)
class RawTransaction:
    """One transaction exactly as the statement describes it, before any cleaning."""

    posted_date: datetime.date
    amount_cents: int
    """Negative = money out, positive = money in."""
    description: str
    """The bank's text, with surrounding whitespace removed but otherwise unchanged."""
    external_id: str | None = None
    """A unique ID from the bank when the format has one (OFX ``FITID``), else ``None``."""

    def __post_init__(self) -> None:
        if not self.description:
            raise ValueError("description must not be empty")
        if self.description != self.description.strip():
            raise ValueError("description must not have surrounding whitespace")
        if self.external_id == "":
            raise ValueError("external_id must be None or non-empty")


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    """The result of reading one statement file."""

    format: StatementFormat
    transactions: tuple[RawTransaction, ...]
    currency: str | None = None
    """ISO 4217 code when the file states it (OFX does; most CSVs don't)."""
    warnings: tuple[str, ...] = ()
    """User-facing notes about rows that were skipped or values that were guessed."""


class StatementParseError(ValueError):
    """The file can't be read as a statement. The message is shown to the user, so it must say
    what is wrong in plain words (e.g. "Row 14 has no date")."""
