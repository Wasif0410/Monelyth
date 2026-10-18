"""Render a generated :class:`~monelyth_engine.demo.generator.Dataset` as statement files.

- ``demo-checking.csv``: ``Date,Description,Amount`` with ISO dates and signed amounts.
- ``demo-credit-card.csv``: ``Transaction Date,Posted Date,Description,Debit,Credit`` with
  MM/DD/YYYY dates; purchases are positive numbers in Debit, payments and refunds in Credit.
- ``demo-checking.ofx``: the checking rows again, as OFX 2.x XML with a unique FITID each.
- ``labels.csv``: the correct category for every row of both CSVs.

Every file uses ``\n`` line endings, so its bytes are the same on every platform.
"""

from __future__ import annotations

import calendar
import csv
import datetime
import io
from collections.abc import Callable, Iterator, Sequence
from typing import Final
from xml.sax.saxutils import escape

from monelyth_engine.demo.generator import Dataset, Row
from monelyth_engine.ingest.csv_statement import CsvLayout, DebitCredit, SignedAmount

CHECKING_CSV: Final = "demo-checking.csv"
CARD_CSV: Final = "demo-credit-card.csv"
CHECKING_OFX: Final = "demo-checking.ofx"
LABELS_CSV: Final = "labels.csv"

CURRENCY: Final = "CAD"
"""The currency the OFX file declares. The CSV files name none, so they import into any."""
CHECKING_OPENING_BALANCE_CENTS: Final = 3_200_00
CHECKING_BANK_ID: Final = "000999001"
CHECKING_ACCOUNT_ID: Final = "0000123456"
OFX_NAME_LIMIT: Final = 32
"""The OFX spec caps NAME at 32 characters; longer text goes in full into MEMO."""

CHECKING_CSV_LAYOUT: Final = CsvLayout(
    encoding="utf-8-sig",
    delimiter=",",
    skip_rows=0,
    has_header=True,
    date_column=0,
    description_column=1,
    amount=SignedAmount(column=2),
    date_format="%Y-%m-%d",
    decimal_separator=".",
    invert_signs=False,
)
"""How :func:`checking_csv` lays out its columns, as a user would confirm it on import."""
CARD_CSV_LAYOUT: Final = CsvLayout(
    encoding="utf-8-sig",
    delimiter=",",
    skip_rows=0,
    has_header=True,
    date_column=1,
    description_column=2,
    amount=DebitCredit(debit_column=3, credit_column=4),
    date_format="%m/%d/%Y",
    decimal_separator=".",
    invert_signs=False,
)
"""How :func:`card_csv` lays out its columns. The posted date is the one stored."""


def sample_files(dataset: Dataset) -> dict[str, str]:
    """Every file in ``sample-data/``, by file name, in the order they are written."""
    renderers: dict[str, Callable[[Dataset], str]] = {
        CHECKING_CSV: checking_csv,
        CARD_CSV: card_csv,
        CHECKING_OFX: checking_ofx,
        LABELS_CSV: labels_csv,
    }
    return {name: render(dataset) for name, render in renderers.items()}


def _csv_text(header: Sequence[str], rows: Iterator[Sequence[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def checking_csv(dataset: Dataset) -> str:
    return _csv_text(
        ("Date", "Description", "Amount"),
        (
            (row.posted.isoformat(), row.description, _money(row.amount_cents))
            for row in dataset.checking
        ),
    )


def card_csv(dataset: Dataset) -> str:
    def cells(row: Row) -> tuple[str, str, str, str, str]:
        debit = _money(-row.amount_cents) if row.amount_cents < 0 else ""
        credit = _money(row.amount_cents) if row.amount_cents > 0 else ""
        return (_us_date(row.transacted), _us_date(row.posted), row.description, debit, credit)

    return _csv_text(
        ("Transaction Date", "Posted Date", "Description", "Debit", "Credit"),
        (cells(row) for row in dataset.card),
    )


def labels_csv(dataset: Dataset) -> str:
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


def checking_ofx(dataset: Dataset) -> str:
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
