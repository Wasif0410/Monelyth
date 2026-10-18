"""Find money moving between the user's own accounts, so it isn't counted as spending.

Paying a credit card shows up twice: money out of checking and the same money into the card.
Moving money to savings does the same. :func:`link_transfers` finds these pairs and links both
sides with a shared ``transfer_group`` and the Transfers category, so totals can leave them out.

Two transactions can be a pair when they are for the same amount with opposite signs, in two
different accounts with the same currency, and posted close together. Wording like "PAYMENT -
THANK YOU" or "ONLINE BANKING TRANSFER" on either side is strong evidence, so such pairs may
be up to :data:`KEYWORD_WINDOW_DAYS` apart; pairs without it must be within
:data:`PLAIN_WINDOW_DAYS`. A category the user chose is never overridden: a side the user put
in any other category is never linked.
"""

from __future__ import annotations

import datetime
import re
import sqlite3
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.models import AccountType, CategorySource, Transaction
from monelyth_engine.db.transactions import get_transaction

TRANSFERS_CATEGORY: Final = "Transfers"
"""The seeded category both sides of a transfer are put in, looked up by name."""

KEYWORD_WINDOW_DAYS: Final = 5
"""How far apart two sides may post when at least one of them reads like a transfer. Money
between banks, and card payments, can take a few business days to arrive."""

PLAIN_WINDOW_DAYS: Final = 1
"""How far apart two sides may post when neither reads like a transfer. Without that evidence
only a near-simultaneous match is convincing; further apart, an equal amount is more likely a
coincidence, such as a refund on one account and a purchase on another."""

_TRANSFER_WORDS: Final = re.compile(
    r"\b(?:e-?transfers?|transfers?|tfr|xfer|payments?|pmt|pymt|autopay|cash advance)\b"
)
"""Wording banks use for money moving between accounts, matched against the casefolded
description: "ONLINE BANKING TRANSFER", "PAYMENT - THANK YOU", "E-TRANSFER TO SELF",
"TFR TO SAVINGS", "AUTOPAY" and the like."""


@dataclass(frozen=True, slots=True)
class _Side:
    """An unlinked transaction that could be one side of a transfer."""

    id: int
    account_id: int
    currency: str
    posted_date: datetime.date
    amount_cents: int
    reads_like_transfer: bool
    user_categorized: bool
    """The user already put it in Transfers; their choice is kept as theirs."""


@dataclass(frozen=True, slots=True)
class _Pair:
    outgoing: _Side
    incoming: _Side
    evidence: int
    """How many of the two sides read like a transfer (0, 1 or 2)."""
    days_apart: int

    @property
    def rank(self) -> tuple[int, int, int, int]:
        """Best first: more evidence, then closer dates, then the older transactions, so the
        same data always pairs up the same way."""
        return (-self.evidence, self.days_apart, self.outgoing.id, self.incoming.id)


def link_transfers(conn: sqlite3.Connection) -> int:
    """Link every newly found transfer pair and return how many pairs were linked.

    Both sides of a pair get the same new ``transfer_group`` and the Transfers category from
    the ``rule`` tier with full confidence, out of the review queue. A side the user already
    put in Transfers keeps the user as its source. Transactions that are already linked are
    left alone, so running this again links nothing new.

    Each transaction is in at most one pair. When several transactions could pair with the
    same one, the pair with the most transfer wording wins, then the one with the closest
    dates; remaining ties go to the older transactions.

    A transfer whose other side was deleted (with its account) is released first, so its
    remaining side can pair again.

    Raises:
        NotFoundError: if the Transfers category does not exist.
    """
    with atomic(conn):
        category_id = _transfers_category_id(conn)
        _release_half_pairs(conn)
        pairs = _pair_up(_unlinked_sides(conn, category_id))
        _link(conn, pairs, category_id)
    return len(pairs)


def unlink_transfer(conn: sqlite3.Connection, transfer_group: str) -> list[Transaction]:
    """Undo a transfer link the user says is wrong, and return the transactions it joined.

    Both sides leave the group. A side that is in Transfers only because it was linked goes
    back to uncategorized and into the review queue, so the user picks its real category; a
    category the user chose stays.

    Unlinked pairs are not recorded anywhere yet, so until the user picks a category other
    than Transfers for one of the sides, a later :func:`link_transfers` may pair them again.

    Raises:
        NotFoundError: if no transaction is linked under ``transfer_group``.
    """
    with atomic(conn):
        ids: list[int] = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM transactions WHERE transfer_group = ? ORDER BY id",
                (transfer_group,),
            )
        ]
        if not ids:
            raise NotFoundError("These transactions are no longer linked as a transfer.")
        conn.execute(
            "UPDATE transactions SET category_id = NULL, category_source = NULL, "
            "confidence = NULL, needs_review = 1 "
            "WHERE transfer_group = ? AND category_id = ? AND category_source IS NOT ?",
            (transfer_group, _transfers_category_id(conn), CategorySource.USER.value),
        )
        conn.execute(
            "UPDATE transactions SET transfer_group = NULL WHERE transfer_group = ?",
            (transfer_group,),
        )
        return [get_transaction(conn, transaction_id) for transaction_id in ids]


def reads_like_transfer(description: str) -> bool:
    """Whether a bank description uses wording for money moving between accounts."""
    return _TRANSFER_WORDS.search(description.casefold()) is not None


def _transfers_category_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM categories WHERE name = ?", (TRANSFERS_CATEGORY,)).fetchone()
    if row is None:
        raise NotFoundError(
            f"The {TRANSFERS_CATEGORY} category is missing, so transfers can't be linked."
        )
    category_id: int = row["id"]
    return category_id


def _release_half_pairs(conn: sqlite3.Connection) -> None:
    """Clear the group of any transaction whose partner no longer exists. Its category stays:
    it still moved money to or from an account, just one Monelyth no longer tracks."""
    conn.execute(
        "UPDATE transactions SET transfer_group = NULL WHERE transfer_group IN ("
        "SELECT transfer_group FROM transactions WHERE transfer_group IS NOT NULL "
        "GROUP BY transfer_group HAVING COUNT(*) = 1)"
    )


def _unlinked_sides(conn: sqlite3.Connection, category_id: int) -> list[_Side]:
    """Every transaction that may still be linked: not linked yet, not zero, and not put in
    another category by the user.

    Money leaving a credit card is a purchase unless the card says otherwise (a cash advance
    or balance transfer), so such a transaction only counts when it reads like a transfer.
    Without this, a friend paying back exactly what was bought for them on the card would
    turn the purchase into a transfer.
    """
    rows = conn.execute(
        "SELECT t.id, t.account_id, a.currency, a.type, t.posted_date, t.amount_cents, "
        "t.description_raw, t.category_source "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.transfer_group IS NULL AND t.amount_cents != 0 "
        "AND (t.category_source IS NOT ? OR t.category_id = ?)",
        (CategorySource.USER.value, category_id),
    )
    sides: list[_Side] = []
    for row in rows:
        wording = reads_like_transfer(row["description_raw"])
        if row["type"] == AccountType.CREDIT_CARD and row["amount_cents"] < 0 and not wording:
            continue
        sides.append(
            _Side(
                id=row["id"],
                account_id=row["account_id"],
                currency=row["currency"],
                posted_date=datetime.date.fromisoformat(row["posted_date"]),
                amount_cents=row["amount_cents"],
                reads_like_transfer=wording,
                user_categorized=row["category_source"] == CategorySource.USER,
            )
        )
    return sides


def _pair_up(sides: Sequence[_Side]) -> list[_Pair]:
    """Choose the pairs greedily, best first, using each transaction at most once.

    Taking the best remaining pair each time also makes the result final: every possible
    pair that was passed over shares a transaction with a chosen one, so a second run over
    what is left finds nothing.
    """
    incoming: defaultdict[tuple[str, int], list[_Side]] = defaultdict(list)
    for side in sides:
        if side.amount_cents > 0:
            incoming[side.currency, side.amount_cents].append(side)

    candidates = sorted(
        (
            pair
            for outgoing in sides
            if outgoing.amount_cents < 0
            for pair in _possible_pairs(
                outgoing, incoming.get((outgoing.currency, -outgoing.amount_cents), ())
            )
        ),
        key=lambda pair: pair.rank,
    )

    taken: set[int] = set()
    chosen: list[_Pair] = []
    for pair in candidates:
        if pair.outgoing.id in taken or pair.incoming.id in taken:
            continue
        taken.update((pair.outgoing.id, pair.incoming.id))
        chosen.append(pair)
    return chosen


def _possible_pairs(outgoing: _Side, matches: Iterable[_Side]) -> Iterable[_Pair]:
    """``outgoing`` paired with each of ``matches`` (same currency, opposite amount) that is in
    another account and posted close enough."""
    for incoming in matches:
        if incoming.account_id == outgoing.account_id:
            continue
        evidence = int(outgoing.reads_like_transfer) + int(incoming.reads_like_transfer)
        days_apart = abs((incoming.posted_date - outgoing.posted_date).days)
        if days_apart <= (KEYWORD_WINDOW_DAYS if evidence else PLAIN_WINDOW_DAYS):
            yield _Pair(outgoing, incoming, evidence, days_apart)


def _link(conn: sqlite3.Connection, pairs: Sequence[_Pair], category_id: int) -> None:
    groups = [(uuid.uuid4().hex, pair) for pair in pairs]
    conn.executemany(
        "UPDATE transactions SET transfer_group = ? WHERE id = ?",
        [(group, side.id) for group, pair in groups for side in (pair.outgoing, pair.incoming)],
    )
    conn.executemany(
        "UPDATE transactions SET category_id = ?, category_source = ?, confidence = 1.0, "
        "needs_review = 0 WHERE id = ?",
        [
            (category_id, CategorySource.RULE.value, side.id)
            for _, pair in groups
            for side in (pair.outgoing, pair.incoming)
            if not side.user_categorized
        ],
    )
