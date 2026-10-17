"""Typed rows returned by the repository functions, and the values they accept.

The database stores dates as ``'YYYY-MM-DD'`` text and timestamps as ISO 8601 text in UTC;
these types expose them as ``datetime.date`` and timezone-aware ``datetime.datetime``.
Money follows the engine-wide rule: integer cents, negative = money out.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import StrEnum

from monelyth_engine.ingest.models import RawTransaction, StatementFormat


class AccountType(StrEnum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    OTHER = "other"


class CategoryKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class CategorySource(StrEnum):
    """What assigned a transaction's category. ``USER`` is never overridden automatically."""

    MEMORY = "memory"
    RULE = "rule"
    CLASSIFIER = "classifier"
    LLM = "llm"
    USER = "user"


@dataclass(frozen=True, slots=True)
class Account:
    id: int
    name: str
    institution: str | None
    type: AccountType
    currency: str
    """ISO 4217 code, e.g. ``"CAD"``."""


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    name: str
    kind: CategoryKind
    parent_id: int | None


@dataclass(frozen=True, slots=True)
class ImportRecord:
    id: int
    account_id: int
    file_name: str
    file_sha256: str
    format: StatementFormat
    imported_at: datetime.datetime
    row_count: int
    """How many transactions the file contained, including any later skipped as duplicates."""


@dataclass(frozen=True, slots=True)
class Transaction:
    id: int
    account_id: int
    import_id: int | None
    posted_date: datetime.date
    amount_cents: int
    description_raw: str
    merchant: str | None
    category_id: int | None
    category_source: CategorySource | None
    confidence: float | None
    """0..1 for automatic categories; ``None`` when the user chose it or nothing has yet."""
    needs_review: bool
    transfer_group: str | None


@dataclass(frozen=True, slots=True)
class NewTransaction:
    """A parsed transaction paired with its cleaned merchant name, ready to be stored."""

    raw: RawTransaction
    merchant: str | None
    """The display name from merchant cleaning, or ``None`` when no name could be derived."""

    def __post_init__(self) -> None:
        if self.merchant is not None and (
            not self.merchant or self.merchant != self.merchant.strip()
        ):
            raise ValueError("merchant must be None or non-empty without surrounding whitespace")


@dataclass(frozen=True, slots=True)
class InsertResult:
    added: int
    skipped_duplicates: int


@dataclass(frozen=True, slots=True)
class TransactionFilter:
    """Conditions for listing transactions. Every field left as ``None`` matches everything."""

    account_id: int | None = None
    date_from: datetime.date | None = None
    """Inclusive."""
    date_to: datetime.date | None = None
    """Inclusive."""
    category_id: int | None = None
    search: str | None = None
    """Case-insensitive substring of the bank description or the merchant name. A blank
    string matches everything."""


@dataclass(frozen=True, slots=True)
class TransactionPage:
    items: tuple[Transaction, ...]
    """Newest first; transactions on the same day keep a stable order."""
    total: int
    """How many transactions match the filter across all pages."""
