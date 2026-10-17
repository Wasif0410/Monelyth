"""Read OFX and QFX statement files (the "Download for Quicken/Money" formats) with ofxtools.

Handles OFX 1.x (SGML with a ``KEY:VALUE`` header), OFX 2.x (XML) and QFX (OFX plus Intuit's
``INTU.*`` tags, which ofxtools skips), for bank (``STMTRS``) and credit-card (``CCSTMTRS``)
statements.

Sign convention: the OFX specification signs ``TRNAMT`` from the account holder's point of
view for every account type: debits are negative and credits positive. A credit-card
purchase is therefore already negative and a card payment positive, which is exactly
Monelyth's rule, so amounts are used as-is and never flipped.

FITID becomes ``external_id``, which deduplication trusts. When a bank reuses a FITID inside
one file, only the first transaction keeps it; the rest get ``None`` and a warning, so they
are deduplicated by content instead of being dropped.

ofxtools exposes every OFX field as an untyped attribute. All of that untyped access stays in
this module: each value is checked with ``isinstance`` (or, where the type is fixed by the
ofxtools model, given a narrow commented annotation) before it reaches typed code.
"""

from __future__ import annotations

import codecs
import datetime
import logging
import re
import warnings
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from decimal import Decimal
from io import BytesIO
from typing import Any, Final

from ofxtools.header import OFXHeaderError
from ofxtools.models.bank.stmt import CCSTMTRS, STMTRS, STMTTRN
from ofxtools.models.ofx import OFX
from ofxtools.Parser import OFXTree
from ofxtools.Types import DT_REGEX

from monelyth_engine.ingest.models import (
    ParsedStatement,
    RawTransaction,
    StatementFormat,
    StatementParseError,
)

MAX_FILE_BYTES: Final = 20 * 1024 * 1024
"""Real statements are a few hundred KB at most; anything bigger is the wrong file."""

# How far into a file to look for an <OFX> tag when deciding between "not an OFX file" and
# "an OFX file with a damaged header".
_SNIFF_BYTES: Final = 4096
_OFX_CLOSING_TAG: Final = b"</OFX>"
_DATE_PART: Final = re.compile(r"(\d{4})(\d{2})(\d{2})")

# ofxtools logs every tag and value it parses at DEBUG level and repeats field values in its
# warnings, so the engine's own debug logging would copy account numbers and transaction text
# into the log. Keep both quiet; real problems surface as StatementParseError instead.
logging.getLogger("ofxtools").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", module=r"ofxtools(\.|$)")


def parse_ofx(data: bytes) -> ParsedStatement:
    """Parse one OFX/QFX file holding one bank or credit-card account.

    Raises:
        StatementParseError: if the file is empty, too large, not OFX, damaged or cut off,
            holds no statement or several accounts, or has a transaction with an invalid
            date or amount. The message is written for the user.
    """
    if not data.strip():
        raise StatementParseError("This file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise StatementParseError(
            f"This file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB, which is far too "
            "big for a bank statement. Check that you picked the right file."
        )

    # Windows tools often prepend a UTF-8 byte-order mark, which hides the OFX header from
    # ofxtools.
    data = data.removeprefix(codecs.BOM_UTF8)
    warning_messages: list[str] = []
    root = _parse_tree(data, warning_messages)
    _reduce_posted_dates_to_dates(root)
    ofx = _convert(root)

    statement = _single_statement(ofx)
    # CURDEF is required and validated against the ISO 4217 list by ofxtools.
    currency: str = statement.curdef
    transactions = _transactions(statement, warning_messages)
    return ParsedStatement(
        format=StatementFormat.OFX,
        transactions=tuple(transactions),
        currency=currency,
        warnings=tuple(warning_messages),
    )


def _parse_tree(data: bytes, warning_messages: list[str]) -> ET.Element:
    """Split off the OFX header and build the element tree, or explain why that failed."""
    try:
        return _run_parser(data)
    except UnicodeDecodeError as error:
        # Many banks declare UTF-8 (or no character set) and then write Windows-1252 bytes,
        # usually an accented merchant name. Reading those bytes as Windows-1252 recovers
        # the text instead of rejecting the whole file.
        try:
            root = _run_parser(data.decode("cp1252").encode("utf-8"))
        except UnicodeDecodeError:
            # Not Windows-1252 either, or non-ASCII bytes inside the header itself.
            raise _damaged() from error
        warning_messages.append(
            "Some characters in this file weren't valid UTF-8, so they were read as "
            "Windows-1252. Check accented names in the descriptions."
        )
        return root


def _run_parser(data: bytes) -> ET.Element:
    # OFX 1.x lets data elements omit their end tags, so ofxtools happily builds a tree from
    # a file cut off mid-download. Every complete OFX file ends with </OFX>.
    is_complete = data.rstrip()[-len(_OFX_CLOSING_TAG) :].upper() == _OFX_CLOSING_TAG
    try:
        root = OFXTree().parse(BytesIO(data))
    except UnicodeDecodeError:
        raise
    except OFXHeaderError as error:
        if b"<OFX>" in data[:_SNIFF_BYTES].upper():
            raise StatementParseError(
                "This OFX file's header is missing or damaged. Download it from your bank again."
            ) from error
        raise StatementParseError(
            "This file isn't an OFX or QFX statement. Export it from your bank using "
            "'Download for Quicken' or 'OFX', or import it as CSV instead."
        ) from error
    # ofxtools raises many undocumented exception types on malformed input (SyntaxError,
    # ValueError, KeyError, ...). This boundary turns all of them into one user-facing error.
    except Exception as error:
        raise (_damaged() if is_complete else _incomplete()) from error

    if not is_complete:
        raise _incomplete()
    return root


def _reduce_posted_dates_to_dates(root: ET.Element) -> None:
    """Replace each ``DTPOSTED`` value with its ``YYYYMMDD`` date part, in place.

    OFX writes timestamps in the bank's local time with an optional UTC offset, e.g.
    ``20260915200000.000[-5:EST]``. ofxtools converts them to UTC, which moves an evening
    transaction west of UTC (or a morning one east of it) to the wrong day. The posting date
    is the date the bank wrote, so the time and offset are validated and then dropped.
    """
    for number, element in enumerate(root.iter("DTPOSTED"), start=1):
        text = (element.text or "").strip()
        match = _DATE_PART.match(text)
        if match is None or DT_REGEX.match(text) is None:
            raise StatementParseError(
                f"Transaction {number} has a date in a format OFX doesn't allow: {text!r}."
            )
        year, month, day = (int(part) for part in match.groups())
        try:
            datetime.date(year, month, day)
        except ValueError as error:
            raise StatementParseError(
                f"Transaction {number} has a date that doesn't exist: {text!r}."
            ) from error
        element.text = match.group(0)


def _convert(root: ET.Element) -> OFX:
    try:
        converted = OFXTree(root).convert()
    # Same boundary as in _run_parser: the file breaks a rule of the OFX specification.
    except Exception as error:
        raise _damaged() from error
    if not isinstance(converted, OFX):
        raise _damaged()
    return converted


def _damaged() -> StatementParseError:
    return StatementParseError(
        "This OFX file is damaged or doesn't follow the OFX standard, so it can't be read. "
        "Download it from your bank again, or export a CSV instead."
    )


def _incomplete() -> StatementParseError:
    return StatementParseError(
        "This OFX file is incomplete. It may have been cut off while downloading; "
        "download it from your bank again."
    )


def _single_statement(ofx: OFX) -> STMTRS | CCSTMTRS:
    # Each message set is an ofxtools aggregate or None; ``statements`` is a list of them.
    bank_statements: list[Any] = ofx.bankmsgsrsv1.statements if ofx.bankmsgsrsv1 else []
    card_statements: list[Any] = ofx.creditcardmsgsrsv1.statements if ofx.creditcardmsgsrsv1 else []
    # Closing-statement summaries (STMTENDRS) carry no transactions; only real statements count.
    statements = [
        statement
        for statement in (*bank_statements, *card_statements)
        if isinstance(statement, STMTRS | CCSTMTRS)
    ]

    if not statements:
        if ofx.invstmtmsgsrsv1:
            raise StatementParseError(
                "This is an investment statement. Monelyth reads bank and credit card "
                "statements only."
            )
        raise StatementParseError("This file has no bank or credit card statement in it.")

    accounts = {_account_key(statement) for statement in statements}
    if len(accounts) > 1:
        raise StatementParseError(
            f"This file has {len(accounts)} accounts. Export one account at a time."
        )
    if len(statements) > 1:
        raise StatementParseError(
            f"This file has {len(statements)} statements for the same account. "
            "Export one statement at a time."
        )
    return statements[0]


def _account_key(statement: STMTRS | CCSTMTRS) -> tuple[str, ...]:
    # ACCTID is required in both account aggregates; BANKID only exists for bank accounts.
    if isinstance(statement, STMTRS):
        account: Any = statement.bankacctfrom
        return ("bank", str(account.bankid), str(account.acctid))
    card: Any = statement.ccacctfrom
    return ("card", str(card.acctid))


def _transactions(
    statement: STMTRS | CCSTMTRS, warning_messages: list[str]
) -> list[RawTransaction]:
    # BANKTRANLIST is optional; when present it is a list of STMTTRN aggregates.
    entries: Sequence[Any] = statement.banktranlist or ()

    transactions: list[RawTransaction] = []
    seen_fitids: set[str] = set()
    corrections = 0
    untitled = 0
    reused_fitids = 0
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, STMTTRN):
            continue
        # CORRECTACTION marks an entry that edits or deletes an earlier one by FITID, not a
        # new transaction. Applying corrections needs the earlier import, so skip them.
        if entry.correctaction is not None:
            corrections += 1
            continue
        description = _description(entry)
        if description is None:
            untitled += 1
            # TRNTYPE is required and limited to OFX's fixed list (DEBIT, ATM, FEE, ...).
            trntype: str = entry.trntype
            description = trntype
        # FITID should be unique, but some banks reuse one within a file. Deduplication keys
        # on it, so a reused one would silently drop a real transaction. Later rows give it
        # up and are deduplicated by their content instead.
        fitid = _text(entry.fitid)
        if fitid is not None and fitid in seen_fitids:
            reused_fitids += 1
            fitid = None
        elif fitid is not None:
            seen_fitids.add(fitid)
        transactions.append(
            RawTransaction(
                posted_date=_posted_date(entry),
                amount_cents=_amount_cents(entry, number),
                description=description,
                external_id=fitid,
            )
        )

    if corrections:
        warning_messages.append(
            f"Skipped {_plural(corrections, 'bank correction', 'bank corrections')} "
            "to transactions from an earlier download."
        )
    if untitled:
        warning_messages.append(
            f"{_plural(untitled, 'transaction has', 'transactions have')} no name or memo, "
            "so the transaction type (such as DEBIT) is used as the description."
        )
    if reused_fitids:
        warning_messages.append(
            f"{_plural(reused_fitids, 'transaction reuses', 'transactions reuse')} the bank ID "
            "(FITID) of an earlier transaction in this file. They were kept; check them for "
            "duplicates."
        )
    return transactions


def _posted_date(entry: STMTTRN) -> datetime.date:
    # DTPOSTED is required; ofxtools returns an aware datetime at midnight UTC because
    # _reduce_posted_dates_to_dates already cut every value down to its date part.
    posted: datetime.datetime = entry.dtposted
    return posted.date()


def _amount_cents(entry: STMTTRN, number: int) -> int:
    amount = entry.trnamt
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise StatementParseError(f"Transaction {number} has an amount that isn't a number.")
    cents = amount.scaleb(2)
    if cents != cents.to_integral_value():
        raise StatementParseError(
            f"Transaction {number} has an amount with a fraction of a cent: {amount}."
        )
    return int(cents)


def _description(entry: STMTTRN) -> str | None:
    """Combine the payee name and memo into one description, or None if both are empty.

    NAME holds at most 32 characters, so banks often put the full text in MEMO (or the
    100-character EXTDNAME) and a copy cut off mid-word in NAME. Repeated text is dropped so
    nothing appears twice; distinct parts are joined with a space, the way the same banks lay
    them out in their CSV exports.
    """
    # PAYEE is an optional aggregate that replaces NAME; its own NAME is required.
    payee: Any = entry.payee
    name = _text(entry.name) or (_text(payee.name) if payee is not None else None)
    return _combine((name, _text(entry.extdname), _text(entry.memo)))


def _combine(parts: Iterable[str | None]) -> str | None:
    """Join the parts in order, skipping repeated text (compared ignoring case and spacing).

    - A part whose words already appear in a kept part is skipped.
    - A part that contains a kept part's words, or that starts with a kept part (a NAME cut
      off at 32 characters), replaces it.

    Word boundaries matter: a MEMO of ``PAY`` is not hidden by a NAME of ``PAYMENT``.
    """
    kept: list[str] = []
    for part in parts:
        if part is None:
            continue
        key = _comparison_key(part)
        if any(_contains_words(_comparison_key(existing), key) for existing in kept):
            continue
        replaced = [
            i
            for i, existing in enumerate(kept)
            if _contains_words(key, _comparison_key(existing))
            or key.startswith(_comparison_key(existing))
        ]
        if replaced:
            # Keep the fuller text where the first part it replaces was.
            kept[replaced[0]] = part
            kept = [existing for i, existing in enumerate(kept) if i not in replaced[1:]]
        else:
            kept.append(part)
    return " ".join(kept) or None


def _contains_words(text: str, words: str) -> bool:
    return f" {words} " in f" {text} "


def _comparison_key(text: str) -> str:
    return " ".join(text.casefold().split())


def _text(value: object) -> str | None:
    """Strip an optional ofxtools string field; blank becomes None."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"
