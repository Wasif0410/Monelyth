"""Generate the fake demo statements in ``sample-data/``.

Usage (from the ``engine`` folder)::

    uv run python scripts/generate_sample_data.py [--end-month YYYY-MM] [--output-dir DIR]

Writes twelve months of made-up activity for one checking account and one credit card, ending
with ``--end-month`` (default 2026-09):

- ``demo-checking.csv``: ``Date,Description,Amount`` with ISO dates and signed amounts.
- ``demo-credit-card.csv``: ``Transaction Date,Posted Date,Description,Debit,Credit`` with
  MM/DD/YYYY dates; purchases are positive numbers in Debit, payments and refunds in Credit.
- ``demo-checking.ofx``: the checking rows again, as OFX 2.x XML with a unique FITID each.
- ``labels.csv``: the correct category for every row of both CSVs.

The output depends only on the arguments: one fixed seed drives every random choice and
nothing reads the clock, so the committed files can be reproduced byte for byte. Everything is
invented: the people, account numbers and local businesses do not exist. Well-known chains and
subscriptions appear only as merchants.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import datetime
import io
import itertools
import random
import string
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape

ENGINE_DIR: Final = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR: Final = ENGINE_DIR.parent / "sample-data"
DEFAULT_END_MONTH: Final = "2026-09"
"""Fixed so the committed files never change unless the generator does."""
SEED: Final = 20260917
MONTHS: Final = 12

CHECKING_CSV: Final = "demo-checking.csv"
CARD_CSV: Final = "demo-credit-card.csv"
CHECKING_OFX: Final = "demo-checking.ofx"
LABELS_CSV: Final = "labels.csv"

CURRENCY: Final = "CAD"
CHECKING_OPENING_BALANCE_CENTS: Final = 3_200_00
CHECKING_BANK_ID: Final = "000999001"
CHECKING_ACCOUNT_ID: Final = "0000123456"
OFX_NAME_LIMIT: Final = 32
"""The OFX spec caps NAME at 32 characters; longer text goes in full into MEMO."""


class Account(StrEnum):
    CHECKING = "checking"
    CREDIT_CARD = "credit_card"


class Category(StrEnum):
    """The default categories seeded in PLAN.md step 1.1, spelled exactly the same."""

    SALARY = "Salary"
    OTHER_INCOME = "Other Income"
    RENT = "Rent/Mortgage"
    UTILITIES = "Utilities"
    GROCERIES = "Groceries"
    DINING_OUT = "Dining Out"
    COFFEE = "Coffee"
    TRANSPORT = "Transport"
    GAS = "Gas"
    RIDESHARE = "Rideshare"
    SHOPPING = "Shopping"
    SUBSCRIPTIONS = "Subscriptions"
    ENTERTAINMENT = "Entertainment"
    HEALTH = "Health"
    EDUCATION = "Education"
    TRAVEL = "Travel"
    FEES = "Fees & Interest"
    GIFTS = "Gifts & Donations"
    TRANSFERS = "Transfers"
    OTHER = "Other"


@dataclass(frozen=True, slots=True)
class Row:
    account: Account
    posted: datetime.date
    description: str
    amount_cents: int
    """Negative = money out of the account, as everywhere in Monelyth."""
    category: Category
    transacted: datetime.date
    """When the purchase happened; card rows post up to a few days later."""
    trntype: str
    """OFX transaction type, written to the OFX file for checking rows."""


@dataclass(frozen=True, slots=True)
class Month:
    year: int
    month: int

    def shifted(self, months: int) -> Month:
        index = self.year * 12 + self.month - 1 + months
        return Month(index // 12, index % 12 + 1)

    def day(self, day: int) -> datetime.date:
        return datetime.date(self.year, self.month, day)

    @property
    def last_day(self) -> datetime.date:
        return self.day(calendar.monthrange(self.year, self.month)[1])


@dataclass(frozen=True, slots=True)
class Merchant:
    description: str
    low_cents: int
    high_cents: int
    category: Category


@dataclass(slots=True)
class Dataset:
    start: datetime.date
    end: datetime.date
    checking: list[Row] = field(default_factory=list[Row])
    card: list[Row] = field(default_factory=list[Row])


# --- Merchants ---------------------------------------------------------------------------
# Local businesses are invented. Ranges are what one purchase costs, in cents.

GROCERY_STORES: Final = (
    Merchant("LOBLAWS #1031 TORONTO ON", 4500, 16500, Category.GROCERIES),
    Merchant("NO FRILLS #3456 TORONTO ON", 3800, 12000, Category.GROCERIES),
    Merchant("T&T SUPERMARKET #021", 3000, 9500, Category.GROCERIES),
    Merchant("FARM BOY #36 TORONTO ON", 2500, 8800, Category.GROCERIES),
)
GROCERY_TOP_UPS: Final = (
    Merchant("POS PURCHASE GREENLEAF ORGANIC MARKET", 800, 3500, Category.GROCERIES),
    Merchant("POS PURCHASE OSSINGTON FRUIT MARKET", 600, 2400, Category.GROCERIES),
)
COFFEE_SHOPS: Final = (
    Merchant("SQ *BLUE BOTTLE 0423 TORONTO ON", 475, 725, Category.COFFEE),
    Merchant("SQ *LITTLE PIGEON CAFE TORONTO ON", 425, 650, Category.COFFEE),
    Merchant("TST* NORTHERN GROUNDS COFFEE", 395, 610, Category.COFFEE),
    Merchant("TIM HORTONS #2851", 225, 495, Category.COFFEE),
    Merchant("STARBUCKS 04312", 450, 795, Category.COFFEE),
)
DUPLICATE_COFFEE: Final = Merchant("SQ *LITTLE PIGEON CAFE TORONTO ON", 525, 525, Category.COFFEE)
"""Bought twice in a row on a few days: two identical rows that are both real."""
RESTAURANTS: Final = (
    Merchant("TST* HARBOUR NOODLE BAR", 2200, 5800, Category.DINING_OUT),
    Merchant("THE ROSEDALE TAVERN TORONTO ON", 3400, 8900, Category.DINING_OUT),
    Merchant("SQ *KENSINGTON TACO CO", 1600, 3900, Category.DINING_OUT),
    Merchant("UBER *EATS HELP.UBER.COM", 2200, 4800, Category.DINING_OUT),
    Merchant("MCDONALD'S #40212", 900, 1650, Category.DINING_OUT),
)
RIDESHARE: Final = Merchant("UBER *TRIP HELP.UBER.COM", 1100, 3800, Category.RIDESHARE)
GAS_STATIONS: Final = (
    Merchant("PETRO-CANADA 12345 TORONTO ON", 3800, 6500, Category.GAS),
    Merchant("SHELL C01234", 3500, 6200, Category.GAS),
)
AMAZON: Final = Merchant("AMZN Mktp CA*", 1299, 8999, Category.SHOPPING)
"""Each order adds its own six-character reference, like ``AMZN Mktp CA*2K4X91``."""
PHARMACY: Final = Merchant("SHOPPERS DRUG MART #1234", 1150, 4800, Category.HEALTH)
CINEMA: Final = Merchant("CINEPLEX #0123 TORONTO ON", 1600, 3800, Category.ENTERTAINMENT)


@dataclass(frozen=True, slots=True)
class OneOff:
    """Something that happens once a year, on a fixed calendar month and day."""

    month: int
    day: int
    account: Account
    description: str
    amount_cents: int
    """Signed like every amount here: negative = money out."""
    category: Category
    trntype: str = "DEBIT"


_CARD: Final = Account.CREDIT_CARD
_BANK: Final = Account.CHECKING

ONE_OFFS: Final = (
    OneOff(1, 9, _CARD, "WINNERS #213 TORONTO ON", -6497, Category.SHOPPING),
    OneOff(1, 26, _CARD, "COURSERA.ORG", -5900, Category.EDUCATION),
    OneOff(2, 13, _CARD, "SQ *BLOOM & STEM FLORIST", -6800, Category.GIFTS),
    OneOff(3, 4, _CARD, "QUEEN ST WEST DENTAL", -18000, Category.HEALTH),
    OneOff(3, 21, _CARD, "HOTEL LE PETIT SAINT-PAUL QC", -18966, Category.TRAVEL),
    OneOff(4, 19, _CARD, "IKEA NORTH YORK", -27948, Category.SHOPPING),
    OneOff(5, 6, _BANK, "CRA TAX REFUND", 84216, Category.OTHER_INCOME, "DEP"),
    OneOff(5, 28, _CARD, "TICKETMASTER CA", -14250, Category.ENTERTAINMENT),
    OneOff(6, 10, _CARD, "ANNUAL FEE", -12000, Category.FEES),
    OneOff(7, 8, _CARD, "AIR CANADA 0142187654321", -48627, Category.TRAVEL),
    OneOff(7, 8, _CARD, "AIRBNB * HMQ4K2X9TZ", -61240, Category.TRAVEL),
    OneOff(8, 30, _CARD, "BEST BUY #957", -37999, Category.SHOPPING),
    OneOff(9, 3, _CARD, "LAKESHORE COLLEGE BOOKSTORE", -8475, Category.EDUCATION),
    OneOff(9, 16, _CARD, "QUEEN ST WEST DENTAL", -9500, Category.HEALTH),
    OneOff(10, 25, _CARD, "WINNERS #213 TORONTO ON", -4299, Category.SHOPPING),
    OneOff(11, 14, _BANK, "E-TRANSFER FROM M. CHEN", 4550, Category.OTHER_INCOME, "CREDIT"),
    OneOff(12, 2, _CARD, "CANADAHELPS*PARKSIDE FOOD BANK", -10000, Category.GIFTS),
    OneOff(12, 12, _CARD, "SQ *BLOOM & STEM FLORIST", -8400, Category.GIFTS),
    OneOff(12, 20, _CARD, "WINNERS #213 TORONTO ON", -11250, Category.SHOPPING),
)


# --- Generation --------------------------------------------------------------------------


def generate(end_month: Month) -> Dataset:
    """Build the twelve months that end with ``end_month``. Same input, same output."""
    first_month = end_month.shifted(-(MONTHS - 1))
    rng = random.Random(SEED)  # noqa: S311 -- seeded on purpose: reproducible fake data
    return _Generator(rng, [first_month.shifted(i) for i in range(MONTHS)], end_month).run()


class _Generator:
    """Adds each kind of activity in a fixed order, so the random draws never move."""

    def __init__(self, rng: random.Random, months: list[Month], end_month: Month) -> None:
        self._rng = rng
        self._months = months
        self._data = Dataset(start=months[0].day(1), end=end_month.last_day)

    def run(self) -> Dataset:
        self._salary()
        self._rent_and_bills()
        self._subscriptions()
        self._groceries()
        self._coffee()
        self._dining_out()
        self._transport()
        self._rideshare_and_gas()
        self._shopping_and_health()
        self._one_offs()
        self._atm_and_fees()
        # Last: each payment covers the card activity of the month before it.
        self._card_payments()

        self._data.checking.sort(key=lambda row: row.posted)
        self._data.card.sort(key=lambda row: (row.posted, row.transacted))
        return self._data

    # --- Checking ------------------------------------------------------------------------

    def _salary(self) -> None:
        start = self._data.start
        payday = start + datetime.timedelta(days=(calendar.FRIDAY - start.weekday()) % 7)
        while payday <= self._data.end:
            self._checking(payday, "PAYROLL ACME CORP", 238462, Category.SALARY, "DIRECTDEP")
            payday += datetime.timedelta(days=14)

    def _rent_and_bills(self) -> None:
        for month in self._months:
            self._checking(
                month.day(1),
                "PREAUTHORIZED DEBIT HARBOURVIEW PROPERTY MGMT",
                -185000,
                Category.RENT,
                "DIRECTDEBIT",
            )
            internet = "PREAUTHORIZED DEBIT BELL CANADA"
            self._checking(month.day(8), internet, -8500, Category.UTILITIES, "DIRECTDEBIT")

            self._checking(
                month.day(12),
                "PREAUTHORIZED DEBIT LAKEPORT HYDRO",
                -self._rng.randint(*_hydro_bill_range(month.month)),
                Category.UTILITIES,
                "DIRECTDEBIT",
            )
            self._checking(
                month.day(18),
                "PREAUTHORIZED DEBIT LAKEPORT GAS",
                -self._rng.randint(*_heating_bill_range(month.month)),
                Category.UTILITIES,
                "DIRECTDEBIT",
            )

    def _atm_and_fees(self) -> None:
        for index, month in enumerate(self._months):
            if index % 2 == 0:
                day = month.day(self._rng.randint(3, 27))
                amount = -self._rng.choice((4000, 6000, 10000))
                self._checking(day, "ATM WITHDRAWAL QUEEN ST W", amount, Category.OTHER, "ATM")
            self._checking(month.last_day, "MONTHLY ACCOUNT FEE", -495, Category.FEES, "SRVCHG")

    def _card_payments(self) -> None:
        """Pay each month's card balance in full from checking on the 22nd of the next month.

        The card shows the payment one to three days later, like a real bank transfer. The
        first month has no earlier card month in the data, so it has no payment.
        """
        for previous, month in itertools.pairwise(self._months):
            balance = -sum(
                row.amount_cents
                for row in self._data.card
                if (row.posted.year, row.posted.month) == (previous.year, previous.month)
                and row.category is not Category.TRANSFERS
            )
            if balance <= 0:
                continue
            paid = month.day(22)
            received = paid + datetime.timedelta(days=self._rng.randint(1, 3))
            self._checking(
                paid, "ONLINE PAYMENT DEMO BANK VISA", -balance, Category.TRANSFERS, "PAYMENT"
            )
            self._data.card.append(
                Row(
                    Account.CREDIT_CARD,
                    received,
                    "PAYMENT - THANK YOU",
                    balance,
                    Category.TRANSFERS,
                    received,
                    "PAYMENT",
                )
            )

    # --- Credit card ---------------------------------------------------------------------

    def _subscriptions(self) -> None:
        for index, month in enumerate(self._months):
            # Netflix raises its price partway through the year.
            netflix = 1899 if index < 7 else 2099
            self._card_on(
                month.day(15), "NETFLIX.COM 866-579-7172", netflix, Category.SUBSCRIPTIONS
            )
            spotify = f"SPOTIFY P{self._code(9)}"
            self._card_on(month.day(3), spotify, 1199, Category.SUBSCRIPTIONS)
            self._card_on(month.day(27), "APPLE.COM/BILL", 399, Category.SUBSCRIPTIONS)
            self._card_on(month.day(20), "ROGERS WIRELESS AUTOPAY", 6500, Category.UTILITIES)

    def _groceries(self) -> None:
        for day in self._days():
            # One big weekend shop, mostly on the card, plus small debit top-ups midweek.
            if day.weekday() == calendar.SATURDAY or (
                day.weekday() == calendar.SUNDAY and self._rng.random() < 0.15
            ):
                store = self._rng.choice(GROCERY_STORES)
                if self._rng.random() < 0.7:
                    self._card_purchase(day, store)
                else:
                    amount = -self._amount(store)
                    self._checking(
                        day, f"POS PURCHASE {store.description}", amount, store.category, "POS"
                    )
            elif day.weekday() in (calendar.TUESDAY, calendar.THURSDAY) and (
                self._rng.random() < 0.35
            ):
                top_up = self._rng.choice(GROCERY_TOP_UPS)
                amount = -self._amount(top_up)
                self._checking(day, top_up.description, amount, top_up.category, "POS")

    def _coffee(self) -> None:
        pair_days = {self._second_saturday(self._months[i]) for i in (2, 6, 10)}
        for day in self._days():
            if day in pair_days:
                # Two identical coffees on the same day, both real (one was for a friend).
                coffee = DUPLICATE_COFFEE
                self._card_on(day, coffee.description, coffee.low_cents, coffee.category, copies=2)
                continue
            chance = 0.6 if day.weekday() < calendar.SATURDAY else 0.35
            if self._rng.random() < chance:
                self._card_purchase(day, self._rng.choice(COFFEE_SHOPS))

    def _dining_out(self) -> None:
        for day in self._days():
            weekend_night = day.weekday() in (calendar.FRIDAY, calendar.SATURDAY)
            if self._rng.random() < (0.4 if weekend_night else 0.1):
                self._card_purchase(day, self._rng.choice(RESTAURANTS))

    def _transport(self) -> None:
        for month in self._months:
            for day in sorted(self._rng.sample(range(1, 29), 2)):
                self._card_on(month.day(day), "PRESTO AUTOLOAD", 5000, Category.TRANSPORT)
            if self._rng.random() < 0.5:
                day = month.day(self._rng.randint(1, 28))
                amount = self._rng.choice((600, 900, 1200))
                self._card_on(day, "GREEN P PARKING #203", amount, Category.TRANSPORT)

    def _rideshare_and_gas(self) -> None:
        for month in self._months:
            for _ in range(self._rng.randint(1, 4)):
                self._card_purchase(month.day(self._rng.randint(1, 28)), RIDESHARE)
            # A weekend car-share trip every couple of months.
            if month.month % 2 == 1:
                station = self._rng.choice(GAS_STATIONS)
                self._card_purchase(self._second_saturday(month), station)

    def _shopping_and_health(self) -> None:
        refunded = False
        for index, month in enumerate(self._months):
            if self._rng.random() < 0.75:
                day = month.day(self._rng.randint(1, 28))
                description = AMAZON.description + self._code(6)
                amount = self._amount(AMAZON)
                self._card_on(day, description, amount, AMAZON.category)
                if not refunded and 3 <= index < MONTHS - 1:
                    # One order goes back: the refund carries the same description.
                    refunded = True
                    self._card_on(
                        day + datetime.timedelta(days=12), description, -amount, AMAZON.category
                    )
            if self._rng.random() < 0.6:
                self._card_purchase(month.day(self._rng.randint(1, 28)), PHARMACY)
            if self._rng.random() < 0.45:
                self._card_purchase(month.day(self._rng.randint(1, 28)), CINEMA)

    def _one_offs(self) -> None:
        for one_off in ONE_OFFS:
            month = next(m for m in self._months if m.month == one_off.month)
            day = month.day(one_off.day)
            if one_off.account is Account.CHECKING:
                self._checking(
                    day,
                    one_off.description,
                    one_off.amount_cents,
                    one_off.category,
                    one_off.trntype,
                )
            else:
                self._card_on(day, one_off.description, -one_off.amount_cents, one_off.category)

    # --- Helpers -------------------------------------------------------------------------

    def _checking(
        self,
        day: datetime.date,
        description: str,
        amount_cents: int,
        category: Category,
        trntype: str,
    ) -> None:
        self._data.checking.append(
            Row(Account.CHECKING, day, description, amount_cents, category, day, trntype)
        )

    def _card_purchase(self, day: datetime.date, merchant: Merchant) -> None:
        self._card_on(day, merchant.description, self._amount(merchant), merchant.category)

    def _card_on(
        self,
        day: datetime.date,
        description: str,
        charge_cents: int,
        category: Category,
        *,
        copies: int = 1,
    ) -> None:
        """Add a card charge (or a credit, when ``charge_cents`` is negative) made on ``day``.

        Most charges post the next day; some the same day, some after two or three days.
        ``copies`` adds identical charges that also post together.
        """
        lag = self._rng.choices((0, 1, 2, 3), weights=(20, 55, 20, 5))[0]
        posted = min(day + datetime.timedelta(days=lag), self._data.end)
        trntype = "DEBIT" if charge_cents > 0 else "CREDIT"
        row = Row(Account.CREDIT_CARD, posted, description, -charge_cents, category, day, trntype)
        self._data.card.extend([row] * copies)

    def _amount(self, merchant: Merchant) -> int:
        return self._rng.randint(merchant.low_cents, merchant.high_cents)

    def _code(self, length: int) -> str:
        return "".join(self._rng.choices(string.ascii_uppercase + string.digits, k=length))

    def _days(self) -> Iterator[datetime.date]:
        day = self._data.start
        while day <= self._data.end:
            yield day
            day += datetime.timedelta(days=1)

    @staticmethod
    def _second_saturday(month: Month) -> datetime.date:
        first = month.day(1)
        return first + datetime.timedelta(days=(calendar.SATURDAY - first.weekday()) % 7 + 7)


def _hydro_bill_range(month: int) -> tuple[int, int]:
    """Air conditioning in summer and long nights in winter raise the electricity bill."""
    if month in (6, 7, 8):
        return (9500, 13000)
    if month in (12, 1, 2):
        return (7000, 9000)
    return (5500, 7500)


def _heating_bill_range(month: int) -> tuple[int, int]:
    """The gas bill is mostly heating, so it is high from November to March."""
    return (11000, 18500) if month in (11, 12, 1, 2, 3) else (2800, 4500)


# --- Output ------------------------------------------------------------------------------


def write_all(dataset: Dataset, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Callable[[Dataset], str]] = {
        CHECKING_CSV: _checking_csv,
        CARD_CSV: _card_csv,
        CHECKING_OFX: _checking_ofx,
        LABELS_CSV: _labels_csv,
    }
    written: list[Path] = []
    for name, render in files.items():
        path = output_dir / name
        # newline="" keeps "\n" on every platform, so the bytes match .gitattributes (LF).
        with path.open("w", encoding="utf-8", newline="") as file:
            file.write(render(dataset))
        written.append(path)
    return written


def _csv_text(header: Sequence[str], rows: Iterator[Sequence[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _checking_csv(dataset: Dataset) -> str:
    return _csv_text(
        ("Date", "Description", "Amount"),
        (
            (row.posted.isoformat(), row.description, _money(row.amount_cents))
            for row in dataset.checking
        ),
    )


def _card_csv(dataset: Dataset) -> str:
    def cells(row: Row) -> tuple[str, str, str, str, str]:
        debit = _money(-row.amount_cents) if row.amount_cents < 0 else ""
        credit = _money(row.amount_cents) if row.amount_cents > 0 else ""
        return (_us_date(row.transacted), _us_date(row.posted), row.description, debit, credit)

    return _csv_text(
        ("Transaction Date", "Posted Date", "Description", "Debit", "Credit"),
        (cells(row) for row in dataset.card),
    )


def _labels_csv(dataset: Dataset) -> str:
    """One row per CSV row, checking first, each in its file's order.

    The date is the posted date, which is what the importers store as ``posted_date``.
    """
    return _csv_text(
        ("account", "date", "description", "amount_cents", "category"),
        (
            (
                row.account,
                row.posted.isoformat(),
                row.description,
                str(row.amount_cents),
                row.category,
            )
            for row in (*dataset.checking, *dataset.card)
        ),
    )


def _checking_ofx(dataset: Dataset) -> str:
    balance = CHECKING_OPENING_BALANCE_CENTS + sum(row.amount_cents for row in dataset.checking)
    end = _ofx_datetime(dataset.end, "235959")
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        '<?OFX OFXHEADER="200" VERSION="220" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>',
        "<OFX>",
        "  <SIGNONMSGSRSV1>",
        "    <SONRS>",
        "      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>",
        f"      <DTSERVER>{end}</DTSERVER>",
        "      <LANGUAGE>ENG</LANGUAGE>",
        "      <FI><ORG>MONELYTH DEMO BANK</ORG><FID>99901</FID></FI>",
        "    </SONRS>",
        "  </SIGNONMSGSRSV1>",
        "  <BANKMSGSRSV1>",
        "    <STMTTRNRS>",
        "      <TRNUID>1</TRNUID>",
        "      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>",
        "      <STMTRS>",
        f"        <CURDEF>{CURRENCY}</CURDEF>",
        "        <BANKACCTFROM>",
        f"          <BANKID>{CHECKING_BANK_ID}</BANKID>",
        f"          <ACCTID>{CHECKING_ACCOUNT_ID}</ACCTID>",
        "          <ACCTTYPE>CHECKING</ACCTTYPE>",
        "        </BANKACCTFROM>",
        "        <BANKTRANLIST>",
        f"          <DTSTART>{_ofx_datetime(dataset.start, '000000')}</DTSTART>",
        f"          <DTEND>{end}</DTEND>",
    ]
    for fitid, row in zip(_fitids(dataset.checking), dataset.checking, strict=True):
        name = row.description[:OFX_NAME_LIMIT].rstrip()
        lines += [
            "          <STMTTRN>",
            f"            <TRNTYPE>{row.trntype}</TRNTYPE>",
            f"            <DTPOSTED>{_ofx_datetime(row.posted, '120000')}</DTPOSTED>",
            f"            <TRNAMT>{_money(row.amount_cents)}</TRNAMT>",
            f"            <FITID>{fitid}</FITID>",
            f"            <NAME>{escape(name)}</NAME>",
        ]
        if name != row.description:
            lines.append(f"            <MEMO>{escape(row.description)}</MEMO>")
        lines.append("          </STMTTRN>")
    lines += [
        "        </BANKTRANLIST>",
        "        <LEDGERBAL>",
        f"          <BALAMT>{_money(balance)}</BALAMT>",
        f"          <DTASOF>{end}</DTASOF>",
        "        </LEDGERBAL>",
        "      </STMTRS>",
        "    </STMTTRNRS>",
        "  </BANKMSGSRSV1>",
        "</OFX>",
    ]
    return "\n".join(lines) + "\n"


def _fitids(rows: Sequence[Row]) -> Iterator[str]:
    """``YYYYMMDD`` plus a per-day counter, like many banks: ``202609040002``."""
    counts: dict[datetime.date, int] = {}
    for row in rows:
        counts[row.posted] = counts.get(row.posted, 0) + 1
        yield f"{row.posted:%Y%m%d}{counts[row.posted]:04d}"


def _ofx_datetime(day: datetime.date, time: str) -> str:
    """Local Toronto time with its UTC offset, as Canadian banks write it."""
    offset = "[-4:EDT]" if _is_eastern_daylight_time(day) else "[-5:EST]"
    return f"{day:%Y%m%d}{time}.000{offset}"


def _is_eastern_daylight_time(day: datetime.date) -> bool:
    """Daylight time runs from the second Sunday of March to the first Sunday of November.

    Only whole days matter here, and the switch happens at 2 a.m., so a transition Sunday
    counts as daylight time in March and standard time in November.
    """
    march_first = datetime.date(day.year, 3, 1)
    starts = march_first + datetime.timedelta(
        days=(calendar.SUNDAY - march_first.weekday()) % 7 + 7
    )
    november_first = datetime.date(day.year, 11, 1)
    ends = november_first + datetime.timedelta(
        days=(calendar.SUNDAY - november_first.weekday()) % 7
    )
    return starts <= day < ends


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def _us_date(day: datetime.date) -> str:
    return f"{day:%m/%d/%Y}"


# --- Command line ------------------------------------------------------------------------


def _parse_month(text: str) -> Month:
    try:
        parsed = datetime.datetime.strptime(text, "%Y-%m")
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {text!r}") from None
    return Month(parsed.year, parsed.month)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the fake demo statements and their category labels."
    )
    parser.add_argument(
        "--end-month",
        type=_parse_month,
        default=_parse_month(DEFAULT_END_MONTH),
        metavar="YYYY-MM",
        help=f"last of the twelve months to generate (default {DEFAULT_END_MONTH})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="folder to write into (default: sample-data/ at the repository root)",
    )
    args = parser.parse_args(argv)
    end_month: Month = args.end_month
    output_dir: Path = args.output_dir

    dataset = generate(end_month)
    for path in write_all(dataset, output_dir):
        print(f"Wrote {path}")
    print(
        f"{len(dataset.checking)} checking and {len(dataset.card)} credit card transactions "
        f"from {dataset.start} to {dataset.end}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
