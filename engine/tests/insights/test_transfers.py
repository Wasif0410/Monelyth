from __future__ import annotations

import datetime
import hashlib
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from monelyth_engine.db.accounts import create_account, delete_account
from monelyth_engine.db.atomic import atomic
from monelyth_engine.db.connection import connect
from monelyth_engine.db.errors import NotFoundError
from monelyth_engine.db.imports import record_import
from monelyth_engine.db.models import (
    Account,
    AccountType,
    CategorySource,
    NewTransaction,
    Transaction,
)
from monelyth_engine.db.transactions import get_transaction, insert_transactions
from monelyth_engine.ingest.models import RawTransaction, StatementFormat
from monelyth_engine.insights.transfers import (
    KEYWORD_WINDOW_DAYS,
    PLAIN_WINDOW_DAYS,
    TRANSFERS_CATEGORY,
    link_transfers,
    reads_like_transfer,
    unlink_transfer,
)


def day(n: int) -> datetime.date:
    return datetime.date(2026, 9, 1) + datetime.timedelta(days=n - 1)


class Ledger:
    """Builds a database of accounts and transactions for one test."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._files = 0

    def account(
        self,
        name: str,
        account_type: AccountType = AccountType.CHECKING,
        currency: str = "CAD",
    ) -> Account:
        return create_account(self.conn, name=name, account_type=account_type, currency=currency)

    def add(self, account: Account, posted: datetime.date, cents: int, description: str) -> int:
        """Import one transaction, the way a statement upload stores it, and return its ID."""
        self._files += 1
        with atomic(self.conn):
            record = record_import(
                self.conn,
                account_id=account.id,
                file_name=f"statement-{self._files}.csv",
                file_sha256=hashlib.sha256(str(self._files).encode()).hexdigest(),
                statement_format=StatementFormat.CSV,
                row_count=1,
            )
            result = insert_transactions(
                self.conn,
                account_id=account.id,
                import_id=record.id,
                items=[NewTransaction(RawTransaction(posted, cents, description, None), None)],
            )
        assert result.added == 1, "an identical row in the same account is a duplicate"
        transaction_id: int = self.conn.execute("SELECT MAX(id) FROM transactions").fetchone()[0]
        return transaction_id

    def categorize(
        self, transaction_id: int, category: str, source: CategorySource, confidence: float | None
    ) -> None:
        self.conn.execute(
            "UPDATE transactions SET category_id = (SELECT id FROM categories WHERE name = ?), "
            "category_source = ?, confidence = ? WHERE id = ?",
            (category, source.value, confidence, transaction_id),
        )

    def get(self, transaction_id: int) -> Transaction:
        return get_transaction(self.conn, transaction_id)

    def groups(self) -> list[tuple[int, int]]:
        """Each linked pair as (lower ID, higher ID), sorted."""
        rows = self.conn.execute(
            "SELECT MIN(id), MAX(id), COUNT(*) FROM transactions "
            "WHERE transfer_group IS NOT NULL GROUP BY transfer_group ORDER BY MIN(id)"
        ).fetchall()
        assert all(row[2] == 2 for row in rows), "every group has exactly two transactions"
        return [(row[0], row[1]) for row in rows]


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(tmp_path / "monelyth.db")
    yield conn
    conn.close()


@pytest.fixture
def ledger(db: sqlite3.Connection) -> Ledger:
    return Ledger(db)


@pytest.fixture
def checking(ledger: Ledger) -> Account:
    return ledger.account("Main Checking")


@pytest.fixture
def card(ledger: Ledger) -> Account:
    return ledger.account("Visa", AccountType.CREDIT_CARD)


@pytest.fixture
def savings(ledger: Ledger) -> Account:
    return ledger.account("Savings", AccountType.SAVINGS)


@pytest.fixture
def transfers_id(db: sqlite3.Connection) -> int:
    category_id: int = db.execute(
        "SELECT id FROM categories WHERE name = ?", (TRANSFERS_CATEGORY,)
    ).fetchone()[0]
    return category_id


def assert_linked(ledger: Ledger, first: int, second: int, transfers_id: int) -> None:
    a, b = ledger.get(first), ledger.get(second)
    assert a.transfer_group is not None
    assert re.fullmatch(r"[0-9a-f]{32}", a.transfer_group)
    assert a.transfer_group == b.transfer_group
    for tx in (a, b):
        assert tx.category_id == transfers_id
        assert tx.category_source is CategorySource.RULE
        assert tx.confidence == 1.0
        assert tx.needs_review is False


def assert_unlinked(ledger: Ledger, *transaction_ids: int) -> None:
    for transaction_id in transaction_ids:
        tx = ledger.get(transaction_id)
        assert tx.transfer_group is None
        assert tx.category_id is None


# --- Pairs that are transfers ------------------------------------------------------------


def test_credit_card_payment_is_linked(
    ledger: Ledger, checking: Account, card: Account, transfers_id: int
) -> None:
    paid = ledger.add(checking, day(22), -69_750, "ONLINE PAYMENT DEMO BANK VISA")
    received = ledger.add(card, day(23), 69_750, "PAYMENT - THANK YOU")

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, paid, received, transfers_id)


def test_checking_to_savings_is_linked(
    ledger: Ledger, checking: Account, savings: Account, transfers_id: int
) -> None:
    sent = ledger.add(checking, day(3), -50_000, "ONLINE BANKING TRANSFER TO SAVINGS")
    arrived = ledger.add(savings, day(3), 50_000, "ONLINE BANKING TRANSFER FROM CHEQUING")

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, sent, arrived, transfers_id)


def test_e_transfer_to_self_is_linked_with_wording_on_one_side(
    ledger: Ledger, checking: Account, transfers_id: int
) -> None:
    other_bank = ledger.account("Other Bank Savings", AccountType.SAVINGS)
    sent = ledger.add(checking, day(10), -25_000, "INTERAC E-TRANSFER TO SELF")
    arrived = ledger.add(other_bank, day(13), 25_000, "DEPOSIT")

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, sent, arrived, transfers_id)


def test_the_incoming_side_may_post_first(
    ledger: Ledger, checking: Account, card: Account, transfers_id: int
) -> None:
    received = ledger.add(card, day(4), 12_000, "PAYMENT THANK YOU")
    paid = ledger.add(checking, day(6), -12_000, "BILL PAYMENT VISA")

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, paid, received, transfers_id)


def test_cash_advance_from_a_card_is_linked(
    ledger: Ledger, checking: Account, card: Account, transfers_id: int
) -> None:
    advance = ledger.add(card, day(8), -20_000, "CASH ADVANCE")
    deposit = ledger.add(checking, day(9), 20_000, "DEPOSIT")

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, advance, deposit, transfers_id)


@pytest.mark.parametrize(
    "description",
    [
        "PAYMENT - THANK YOU",
        "PAYMENT THANK YOU",
        "ONLINE PAYMENT DEMO BANK VISA",
        "ONLINE BANKING TRANSFER",
        "INTERAC E-TRANSFER TO SELF",
        "etransfer to savings",
        "Internet Transfers",
        "TFR TO 1234567",
        "XFER FROM SAVINGS",
        "CREDIT CARD PMT",
        "AMEX PYMT",
        "AUTOPAY",
        "Cash Advance",
    ],
)
def test_transfer_wording_is_recognized(description: str) -> None:
    assert reads_like_transfer(description)


@pytest.mark.parametrize(
    "description",
    ["PAYROLL ACME CORP", "SQ *BLUE BOTTLE", "PAYMENTUS UTILITY", "TRANSFERWISE", "DEPOSIT"],
)
def test_other_wording_is_not_mistaken_for_a_transfer(description: str) -> None:
    assert not reads_like_transfer(description)


# --- Pairs that are not transfers --------------------------------------------------------


@pytest.mark.parametrize(
    ("days_apart", "descriptions", "linked"),
    [
        (KEYWORD_WINDOW_DAYS, ("ONLINE PAYMENT VISA", "PAYMENT - THANK YOU"), True),
        (KEYWORD_WINDOW_DAYS + 1, ("ONLINE PAYMENT VISA", "PAYMENT - THANK YOU"), False),
        (PLAIN_WINDOW_DAYS, ("CHEQUE 104", "DEPOSIT"), True),
        (PLAIN_WINDOW_DAYS + 1, ("CHEQUE 104", "DEPOSIT"), False),
    ],
)
def test_sides_must_post_within_the_window(
    ledger: Ledger,
    checking: Account,
    savings: Account,
    days_apart: int,
    descriptions: tuple[str, str],
    linked: bool,
) -> None:
    sent = ledger.add(checking, day(1), -30_000, descriptions[0])
    arrived = ledger.add(savings, day(1 + days_apart), 30_000, descriptions[1])

    assert link_transfers(ledger.conn) == int(linked)

    assert (ledger.get(sent).transfer_group is not None) is linked
    assert (ledger.get(arrived).transfer_group is not None) is linked


def test_two_transactions_in_the_same_account_are_never_linked(
    ledger: Ledger, checking: Account
) -> None:
    out = ledger.add(checking, day(5), -10_000, "TRANSFER TO SAVINGS")
    back = ledger.add(checking, day(5), 10_000, "TRANSFER FROM SAVINGS")

    assert link_transfers(ledger.conn) == 0

    assert_unlinked(ledger, out, back)


def test_accounts_in_different_currencies_are_never_linked(
    ledger: Ledger, checking: Account
) -> None:
    us_card = ledger.account("US Visa", AccountType.CREDIT_CARD, currency="USD")
    paid = ledger.add(checking, day(22), -40_000, "ONLINE PAYMENT US VISA")
    received = ledger.add(us_card, day(23), 40_000, "PAYMENT - THANK YOU")

    assert link_transfers(ledger.conn) == 0

    assert_unlinked(ledger, paid, received)


def test_same_sign_amounts_are_never_linked(
    ledger: Ledger, checking: Account, savings: Account
) -> None:
    first = ledger.add(checking, day(5), -10_000, "TRANSFER TO SAVINGS")
    second = ledger.add(savings, day(5), -10_000, "TRANSFER TO CHEQUING")

    assert link_transfers(ledger.conn) == 0

    assert_unlinked(ledger, first, second)


def test_different_amounts_are_never_linked(
    ledger: Ledger, checking: Account, card: Account
) -> None:
    paid = ledger.add(checking, day(22), -40_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(22), 40_001, "PAYMENT - THANK YOU")

    assert link_transfers(ledger.conn) == 0

    assert_unlinked(ledger, paid, received)


def test_a_card_purchase_paid_back_by_a_friend_is_not_a_transfer(
    ledger: Ledger, checking: Account, card: Account
) -> None:
    tickets = ledger.add(card, day(12), -12_000, "TICKETMASTER CANADA")
    repaid = ledger.add(checking, day(12), 12_000, "E-TRANSFER FROM J. DOE")

    assert link_transfers(ledger.conn) == 0

    assert_unlinked(ledger, tickets, repaid)


def test_zero_amounts_are_ignored(ledger: Ledger, checking: Account, savings: Account) -> None:
    first = ledger.add(checking, day(5), 0, "TRANSFER")
    second = ledger.add(savings, day(5), 0, "TRANSFER")

    assert link_transfers(ledger.conn) == 0

    assert_unlinked(ledger, first, second)


# --- Choosing between candidates ---------------------------------------------------------


def test_the_closest_of_three_candidates_wins(
    ledger: Ledger, checking: Account, card: Account, savings: Account, transfers_id: int
) -> None:
    other_savings = ledger.account("Second Savings", AccountType.SAVINGS)
    sent = ledger.add(checking, day(10), -50_000, "ONLINE BANKING TRANSFER")
    three_days = ledger.add(savings, day(13), 50_000, "DEPOSIT")
    one_day = ledger.add(other_savings, day(9), 50_000, "DEPOSIT")
    two_days = ledger.add(card, day(12), 50_000, "DEPOSIT")

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, sent, one_day, transfers_id)
    assert_unlinked(ledger, three_days, two_days)


def test_wording_on_both_sides_beats_a_closer_date(
    ledger: Ledger, checking: Account, card: Account, savings: Account, transfers_id: int
) -> None:
    paid = ledger.add(checking, day(20), -80_000, "ONLINE PAYMENT VISA")
    deposit = ledger.add(savings, day(20), 80_000, "DEPOSIT")
    received = ledger.add(card, day(23), 80_000, "PAYMENT - THANK YOU")

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, paid, received, transfers_id)
    assert_unlinked(ledger, deposit)


def test_each_transaction_is_in_at_most_one_pair(
    ledger: Ledger, checking: Account, savings: Account, transfers_id: int
) -> None:
    first_out = ledger.add(checking, day(1), -10_000, "TRANSFER TO SAVINGS")
    first_in = ledger.add(savings, day(2), 10_000, "TRANSFER FROM CHEQUING")
    second_out = ledger.add(checking, day(4), -10_000, "TRANSFER TO SAVINGS")
    second_in = ledger.add(savings, day(5), 10_000, "TRANSFER FROM CHEQUING")

    assert link_transfers(ledger.conn) == 2

    assert ledger.groups() == [(first_out, first_in), (second_out, second_in)]
    for transaction_id in (first_out, first_in, second_out, second_in):
        assert ledger.get(transaction_id).category_id == transfers_id


def test_ties_go_to_the_older_transaction(
    ledger: Ledger, checking: Account, savings: Account
) -> None:
    sent = ledger.add(checking, day(10), -10_000, "TRANSFER TO SAVINGS")
    older = ledger.add(savings, day(10), 10_000, "TRANSFER FROM CHEQUING")
    newer = ledger.add(savings, day(10), 10_000, "ONLINE TRANSFER FROM CHEQUING")

    assert link_transfers(ledger.conn) == 1

    assert ledger.groups() == [(sent, older)]
    assert_unlinked(ledger, newer)


def _build_tangle(ledger: Ledger) -> None:
    checking = ledger.account("Main Checking")
    savings = ledger.account("Savings", AccountType.SAVINGS)
    card = ledger.account("Visa", AccountType.CREDIT_CARD)
    for n in range(1, 8):
        ledger.add(checking, day(n), -10_000, "TRANSFER TO SAVINGS")
        ledger.add(savings, day(n + n % 3), 10_000, "TRANSFER FROM CHEQUING")
        ledger.add(card, day(n + 1), 10_000, "PAYMENT - THANK YOU")


def test_results_are_deterministic(tmp_path: Path) -> None:
    results: list[list[tuple[int, int]]] = []
    for name in ("first", "second"):
        conn = connect(tmp_path / f"{name}.db")
        try:
            ledger = Ledger(conn)
            _build_tangle(ledger)
            assert link_transfers(conn) == 7
            results.append(ledger.groups())
        finally:
            conn.close()

    assert results[0] == results[1]


# --- Running again -----------------------------------------------------------------------


def test_running_again_links_nothing_new(ledger: Ledger) -> None:
    _build_tangle(ledger)
    assert link_transfers(ledger.conn) == 7
    groups = dict(
        ledger.conn.execute(
            "SELECT id, transfer_group FROM transactions WHERE transfer_group IS NOT NULL"
        ).fetchall()
    )

    assert link_transfers(ledger.conn) == 0

    after = dict(
        ledger.conn.execute(
            "SELECT id, transfer_group FROM transactions WHERE transfer_group IS NOT NULL"
        ).fetchall()
    )
    assert after == groups


def test_a_later_import_links_only_the_new_pair(
    ledger: Ledger, checking: Account, card: Account, transfers_id: int
) -> None:
    ledger.add(checking, day(1), -10_000, "ONLINE PAYMENT VISA")
    ledger.add(card, day(2), 10_000, "PAYMENT - THANK YOU")
    assert link_transfers(ledger.conn) == 1
    first = ledger.groups()

    paid = ledger.add(checking, day(20), -10_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(21), 10_000, "PAYMENT - THANK YOU")

    assert link_transfers(ledger.conn) == 1

    assert ledger.groups() == [*first, (paid, received)]
    assert_linked(ledger, paid, received, transfers_id)


def test_a_side_left_alone_by_a_deleted_account_can_pair_again(
    ledger: Ledger, checking: Account, card: Account, savings: Account, transfers_id: int
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE BANKING TRANSFER")
    ledger.add(card, day(22), 30_000, "PAYMENT - THANK YOU")
    assert link_transfers(ledger.conn) == 1
    delete_account(ledger.conn, card.id)
    saved = ledger.add(savings, day(24), 30_000, "DEPOSIT")

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, paid, saved, transfers_id)


def test_a_side_whose_partner_was_deleted_keeps_its_category(
    ledger: Ledger, checking: Account, card: Account, transfers_id: int
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE PAYMENT VISA")
    ledger.add(card, day(23), 30_000, "PAYMENT - THANK YOU")
    assert link_transfers(ledger.conn) == 1
    delete_account(ledger.conn, card.id)

    assert link_transfers(ledger.conn) == 0

    tx = ledger.get(paid)
    assert tx.transfer_group is None
    assert tx.category_id == transfers_id
    assert tx.category_source is CategorySource.RULE


# --- The user's categories ---------------------------------------------------------------


def test_a_side_the_user_put_elsewhere_is_never_linked(
    ledger: Ledger, checking: Account, card: Account
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(23), 30_000, "PAYMENT - THANK YOU")
    ledger.categorize(received, "Other Income", CategorySource.USER, None)

    assert link_transfers(ledger.conn) == 0

    assert_unlinked(ledger, paid)
    tx = ledger.get(received)
    assert tx.transfer_group is None
    assert tx.category_source is CategorySource.USER


def test_a_side_the_user_put_in_transfers_keeps_the_user_as_source(
    ledger: Ledger, checking: Account, card: Account, transfers_id: int
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(23), 30_000, "PAYMENT - THANK YOU")
    ledger.categorize(received, TRANSFERS_CATEGORY, CategorySource.USER, None)

    assert link_transfers(ledger.conn) == 1

    mine, theirs = ledger.get(received), ledger.get(paid)
    assert mine.transfer_group is not None
    assert mine.transfer_group == theirs.transfer_group
    assert mine.category_id == transfers_id
    assert mine.category_source is CategorySource.USER
    assert mine.confidence is None
    assert theirs.category_source is CategorySource.RULE


def test_an_automatic_category_is_replaced(
    ledger: Ledger, checking: Account, card: Account, transfers_id: int
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(23), 30_000, "PAYMENT - THANK YOU")
    ledger.categorize(paid, "Shopping", CategorySource.CLASSIFIER, 0.55)
    ledger.conn.execute("UPDATE transactions SET needs_review = 1 WHERE id = ?", (paid,))

    assert link_transfers(ledger.conn) == 1

    assert_linked(ledger, paid, received, transfers_id)


# --- Unlinking ---------------------------------------------------------------------------


def test_unlinking_returns_both_sides_to_review(
    ledger: Ledger, checking: Account, card: Account
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(23), 30_000, "PAYMENT - THANK YOU")
    link_transfers(ledger.conn)
    group = ledger.get(paid).transfer_group
    assert group is not None

    unlinked = unlink_transfer(ledger.conn, group)

    assert [tx.id for tx in unlinked] == [paid, received]
    assert unlinked == [ledger.get(paid), ledger.get(received)]
    for tx in unlinked:
        assert tx.transfer_group is None
        assert tx.category_id is None
        assert tx.category_source is None
        assert tx.confidence is None
        assert tx.needs_review is True


def test_unlinking_keeps_the_users_category(
    ledger: Ledger, checking: Account, card: Account, transfers_id: int
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(23), 30_000, "PAYMENT - THANK YOU")
    ledger.categorize(received, TRANSFERS_CATEGORY, CategorySource.USER, None)
    link_transfers(ledger.conn)
    group = ledger.get(paid).transfer_group
    assert group is not None

    unlink_transfer(ledger.conn, group)

    mine = ledger.get(received)
    assert mine.transfer_group is None
    assert mine.category_id == transfers_id
    assert mine.category_source is CategorySource.USER
    assert mine.needs_review is False


def test_an_unlinked_pair_the_user_recategorized_is_not_linked_again(
    ledger: Ledger, checking: Account, card: Account
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(23), 30_000, "PAYMENT - THANK YOU")
    link_transfers(ledger.conn)
    group = ledger.get(paid).transfer_group
    assert group is not None
    unlink_transfer(ledger.conn, group)
    ledger.categorize(received, "Other Income", CategorySource.USER, None)

    assert link_transfers(ledger.conn) == 0

    assert_unlinked(ledger, paid)


def test_unlinking_an_unknown_group_is_refused(ledger: Ledger) -> None:
    with pytest.raises(NotFoundError, match="no longer linked"):
        unlink_transfer(ledger.conn, "0" * 32)


# --- Failure -----------------------------------------------------------------------------


def test_a_missing_transfers_category_is_reported_and_nothing_changes(
    ledger: Ledger, checking: Account, card: Account
) -> None:
    paid = ledger.add(checking, day(22), -30_000, "ONLINE PAYMENT VISA")
    received = ledger.add(card, day(23), 30_000, "PAYMENT - THANK YOU")
    ledger.conn.execute(
        "UPDATE categories SET name = 'Moving Money' WHERE name = ?", (TRANSFERS_CATEGORY,)
    )

    with pytest.raises(NotFoundError, match="Transfers category is missing"):
        link_transfers(ledger.conn)

    assert_unlinked(ledger, paid, received)
    assert not ledger.conn.in_transaction
