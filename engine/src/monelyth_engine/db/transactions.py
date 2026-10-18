"""Storing, deduplicating, listing and editing transactions."""

from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Final

from monelyth_engine.db.atomic import atomic, read_snapshot
from monelyth_engine.db.categories import require_category
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.models import (
    CategorySource,
    InsertResult,
    NewTransaction,
    Transaction,
    TransactionFilter,
    TransactionPage,
)
from monelyth_engine.ingest.models import RawTransaction

_SELECT: Final = (
    "SELECT id, account_id, import_id, posted_date, amount_cents, description_raw, merchant, "
    "category_id, category_source, confidence, needs_review, transfer_group FROM transactions"
)


def fingerprints(account_id: int, transactions: Sequence[RawTransaction]) -> list[str]:
    """The deduplication key for each transaction in one statement, in the same order.

    - With a bank ID (OFX ``FITID``) the key is the account plus that ID, which is exact.
    - Otherwise it is the account, date, amount, description and ``n``, where ``n`` counts the
      earlier rows in this statement with the same date, amount and description. Two real $5
      coffees on one day get ``n`` = 0 and 1, so both are kept; importing an overlapping
      statement later produces the same keys for the shared rows, so they are skipped.

    The fields are hashed as a JSON array, which cannot be ambiguous: no choice of description
    text can make two different rows encode to the same bytes. The leading tag keeps the two
    kinds of key apart.
    """
    seen: Counter[tuple[datetime.date, int, str]] = Counter()
    keys: list[str] = []
    for tx in transactions:
        if tx.external_id is not None:
            keys.append(_digest("fitid", account_id, tx.external_id))
            continue
        identity = (tx.posted_date, tx.amount_cents, tx.description)
        n = seen[identity]
        seen[identity] += 1
        keys.append(
            _digest(
                "row", account_id, tx.posted_date.isoformat(), tx.amount_cents, tx.description, n
            )
        )
    return keys


def insert_transactions(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    import_id: int,
    items: Iterable[NewTransaction],
) -> InsertResult:
    """Store one statement's transactions, skipping any already stored for this account.

    ``items`` must be the whole statement in file order, because the duplicate check for rows
    without a bank ID depends on each row's position among identical rows (see
    :func:`fingerprints`). New rows start uncategorized.

    All rows are inserted or none are. Call this inside the same
    :func:`~monelyth_engine.db.atomic.atomic` block as
    :func:`~monelyth_engine.db.imports.record_import` so the import record is undone too.

    Raises:
        NotFoundError: if the import does not exist.
        ValueError: if the import belongs to a different account.
    """
    batch = tuple(items)
    keys = fingerprints(account_id, [item.raw for item in batch])
    with atomic(conn):
        row = conn.execute("SELECT account_id FROM imports WHERE id = ?", (import_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Import {import_id} does not exist")
        if row["account_id"] != account_id:
            raise ValueError(
                f"Import {import_id} belongs to account {row['account_id']}, not {account_id}"
            )
        if not batch:
            return InsertResult(added=0, skipped_duplicates=0)
        cursor = conn.executemany(
            "INSERT INTO transactions "
            "(account_id, import_id, posted_date, amount_cents, description_raw, merchant, "
            "fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (fingerprint) DO NOTHING",
            [
                (
                    account_id,
                    import_id,
                    item.raw.posted_date.isoformat(),
                    item.raw.amount_cents,
                    item.raw.description,
                    item.merchant,
                    key,
                )
                for item, key in zip(batch, keys, strict=True)
            ],
        )
        # For executemany, rowcount is the total number of rows actually inserted.
        added = cursor.rowcount
    return InsertResult(added=added, skipped_duplicates=len(batch) - added)


def get_transaction(conn: sqlite3.Connection, transaction_id: int) -> Transaction:
    """Raises: NotFoundError: if there is no such transaction."""
    row = conn.execute(f"{_SELECT} WHERE id = ?", (transaction_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Transaction {transaction_id} does not exist")
    return _to_transaction(row)


def list_transactions(
    conn: sqlite3.Connection,
    filters: TransactionFilter | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> TransactionPage:
    """One page of transactions matching ``filters``, newest first, plus the total match count.

    Transactions on the same day are ordered by newest-stored first, so paging through
    them never repeats or skips a row.

    Raises:
        ValueError: if ``limit`` is not positive or ``offset`` is negative.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must not be negative")

    where, params = _where_clause(filters or TransactionFilter())
    with read_snapshot(conn):
        total: int = conn.execute(
            f"SELECT COUNT(*) FROM transactions{where}",  # noqa: S608 -- only fixed fragments
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"{_SELECT}{where} ORDER BY posted_date DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return TransactionPage(items=tuple(_to_transaction(row) for row in rows), total=total)


def transaction_date_range(
    conn: sqlite3.Connection,
) -> tuple[datetime.date, datetime.date] | None:
    """The earliest and latest ``posted_date`` of all stored transactions, or ``None`` when
    there are none yet."""
    row = conn.execute("SELECT MIN(posted_date), MAX(posted_date) FROM transactions").fetchone()
    first: str | None = row[0]
    last: str | None = row[1]
    if first is None or last is None:
        return None
    return datetime.date.fromisoformat(first), datetime.date.fromisoformat(last)


def update_transaction(
    conn: sqlite3.Connection,
    transaction_id: int,
    *,
    category_id: int | None = None,
    merchant: str | None = None,
) -> Transaction:
    """Apply the user's edits to a transaction and return it. ``None`` leaves a field as is.

    A category chosen here is the user's decision: it is marked ``category_source='user'``,
    has no confidence score and leaves the review queue, so automatic categorization will
    not overwrite it.

    Raises:
        NotFoundError: if the transaction or category does not exist.
        ValueError: if nothing is being changed, or the merchant name is blank.
    """
    if category_id is None and merchant is None:
        raise ValueError("Give a category, a merchant name, or both")
    if merchant is not None:
        merchant = merchant.strip()
        if not merchant:
            raise ValueError("Merchant name must not be empty")

    with atomic(conn):
        get_transaction(conn, transaction_id)
        if category_id is not None:
            require_category(conn, category_id)
            conn.execute(
                "UPDATE transactions SET category_id = ?, category_source = ?, "
                "confidence = NULL, needs_review = 0 WHERE id = ?",
                (category_id, CategorySource.USER.value, transaction_id),
            )
        if merchant is not None:
            conn.execute(
                "UPDATE transactions SET merchant = ? WHERE id = ?", (merchant, transaction_id)
            )
        return get_transaction(conn, transaction_id)


def _where_clause(filters: TransactionFilter) -> tuple[str, list[object]]:
    """Build the WHERE clause from fixed SQL fragments; every value is a bound parameter."""
    clauses: list[str] = []
    params: list[object] = []
    if filters.account_id is not None:
        clauses.append("account_id = ?")
        params.append(filters.account_id)
    if filters.date_from is not None:
        clauses.append("posted_date >= ?")
        params.append(filters.date_from.isoformat())
    if filters.date_to is not None:
        clauses.append("posted_date <= ?")
        params.append(filters.date_to.isoformat())
    if filters.category_id is not None:
        clauses.append("category_id = ?")
        params.append(filters.category_id)
    if filters.categorized is not None:
        clauses.append("category_id IS NOT NULL" if filters.categorized else "category_id IS NULL")
    if filters.needs_review is not None:
        clauses.append("needs_review = ?")
        params.append(int(filters.needs_review))
    search = (filters.search or "").strip()
    if search:
        # instr() rather than LIKE, so '%' and '_' in the search text are matched literally.
        clauses.append(
            "(instr(casefold(description_raw), ?) > 0 OR instr(casefold(merchant), ?) > 0)"
        )
        params.extend([search.casefold()] * 2)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _digest(*fields: str | int) -> str:
    # ensure_ascii (the default) escapes every non-ASCII character, so even unusual text,
    # such as a lone surrogate from a badly decoded file, always encodes.
    payload = json.dumps(fields, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _to_transaction(row: sqlite3.Row) -> Transaction:
    source = row["category_source"]
    return Transaction(
        id=row["id"],
        account_id=row["account_id"],
        import_id=row["import_id"],
        posted_date=datetime.date.fromisoformat(row["posted_date"]),
        amount_cents=row["amount_cents"],
        description_raw=row["description_raw"],
        merchant=row["merchant"],
        category_id=row["category_id"],
        category_source=None if source is None else CategorySource(source),
        confidence=row["confidence"],
        needs_review=bool(row["needs_review"]),
        transfer_group=row["transfer_group"],
    )
