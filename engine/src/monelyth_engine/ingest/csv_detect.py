"""Guess the layout of a CSV statement and list what the user still has to decide.

CSV has no standard layout, so detection works like a person reading the file: find the row of
column names (skipping account details above it), match the names against words banks use, and
fall back to the data itself (a column of dates, a column of numbers) when the names don't help.
Anything it can't decide for certain is left unset and turned into a question for the UI.

Only the first rows are used for guessing, so time and memory stay bounded on huge or hostile
files; the chosen date and amount columns are then checked against every row.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import itertools
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from typing import Final

from monelyth_engine.ingest.csv_layout import (
    DELIMITERS,
    AmountColumns,
    CsvLayout,
    CsvLayoutDraft,
    DebitCredit,
    Delimiter,
    SignedAmount,
)
from monelyth_engine.ingest.csv_parse import (
    is_summary_label,
    iter_transactions,
    normalize_header,
    repeats_header,
)
from monelyth_engine.ingest.csv_reader import cell_at, decode_detected, iter_rows
from monelyth_engine.ingest.csv_values import (
    DATE_FORMATS,
    DECIMAL_SEPARATORS,
    CsvValueError,
    DecimalSeparator,
    clean_description,
    date_format_label,
    has_credit_debit_marker,
    is_blank,
    match_date,
    parse_amount,
    quote,
)
from monelyth_engine.ingest.models import RawTransaction, StatementParseError

PREVIEW_ROWS: Final = 10

_HEADER_SEARCH_ROWS: Final = 30
"""How far down the header may be. Preambles are a handful of lines."""
_GUESS_SAMPLE_ROWS: Final = 500
"""Rows below the header used to guess columns from their contents."""
_DELIMITER_SAMPLE_CHARS: Final = 64 * 1024
_DELIMITER_SAMPLE_ROWS: Final = 50
_SNIFF_SAMPLE_CHARS: Final = 4 * 1024
"""``csv.Sniffer`` can take quadratic time on adversarial text, so it only sees a small sample."""
_MIN_FILL: Final = 0.9
"""Share of rows that must have a value for a column to count as always filled."""
_SIGNATURE_PREFIX: Final = b"monelyth-csv-header-v1\n"
"""Versions the signature, so changing how headers are normalised can't collide with old keys."""


class CsvQuestionKind(StrEnum):
    """What the UI must ask before the file can be imported."""

    COLUMNS_GUESSED = "columns_guessed"
    """Columns were picked from the data, not from header names, so the user should check them."""
    NO_DATE_COLUMN = "no_date_column"
    NO_DESCRIPTION_COLUMN = "no_description_column"
    NO_AMOUNT_COLUMN = "no_amount_column"
    DATE_FORMAT_UNKNOWN = "date_format_unknown"
    """No supported format reads every date in the date column."""
    DATE_ORDER_AMBIGUOUS = "date_order_ambiguous"
    """Several formats read every date, differently (every day is 12 or less)."""
    AMOUNT_FORMAT_UNKNOWN = "amount_format_unknown"
    SIGN_CONVENTION_UNKNOWN = "sign_convention_unknown"
    """It can't be told whether purchases are negative (bank style) or positive (card style)."""
    ROW_UNREADABLE = "row_unreadable"
    """The guessed layout is complete, but a row can't be read with it."""


@dataclass(frozen=True, slots=True)
class CsvQuestion:
    kind: CsvQuestionKind
    message: str
    """Plain-language text to show the user."""
    options: tuple[str, ...] = ()
    """For ``DATE_ORDER_AMBIGUOUS``: the date formats that fit every row, most likely first."""


@dataclass(frozen=True, slots=True)
class CsvDetection:
    layout: CsvLayoutDraft
    header_signature: str | None
    """Hex SHA-256 of the normalised header cells, or ``None`` when the file has no header."""
    columns: tuple[str, ...]
    """Column names from the header, or ``"Column 1"``, ``"Column 2"``... where there are none."""
    preview: tuple[RawTransaction, ...]
    """The first :data:`PREVIEW_ROWS` transactions, when the layout is complete."""
    questions: tuple[CsvQuestion, ...]
    """Empty when the layout is complete and every row reads with it."""


class _Role(Enum):
    DATE = auto()
    DESCRIPTION = auto()
    AMOUNT = auto()
    DEBIT = auto()
    CREDIT = auto()
    BALANCE = auto()


# Header names banks use, compared after _normalize_name. Within a role the earlier name wins
# when a file has several: the posting date beats the transaction date, because RawTransaction
# holds the posting date, and "Description" beats "Memo".
_HEADER_NAMES: Final[dict[_Role, tuple[str, ...]]] = {
    _Role.DATE: (
        "posted date",
        "posting date",
        "post date",
        "date posted",
        "booking date",
        "buchungstag",
        "buchungsdatum",
        "date",
        "transaction date",
        "trans date",
        "txn date",
        "date operation",
        "datum",
        "fecha",
        "value date",
        "valuta",
        "wertstellung",
    ),
    _Role.DESCRIPTION: (
        "description",
        "transaction description",
        "description 1",
        "details",
        "transaction details",
        "merchant",
        "merchant name",
        "payee",
        "name",
        "narrative",
        "particulars",
        "beschreibung",
        "verwendungszweck",
        "libelle",
        "descripcion",
        "concepto",
        "omschrijving",
        "transaction",
        "memo",
        "reference",
        "description 2",
    ),
    _Role.AMOUNT: (
        "amount",
        "transaction amount",
        "amt",
        "betrag",
        "montant",
        "importe",
        "bedrag",
    ),
    _Role.DEBIT: (
        "debit",
        "debits",
        "debit amount",
        "withdrawal",
        "withdrawals",
        "withdrawal amount",
        "money out",
        "paid out",
        "outflow",
        "soll",
    ),
    _Role.CREDIT: (
        "credit",
        "credits",
        "credit amount",
        "deposit",
        "deposits",
        "deposit amount",
        "money in",
        "paid in",
        "inflow",
        "haben",
    ),
    _Role.BALANCE: ("balance", "running balance", "available balance", "saldo", "solde"),
}
_NAME_RANKS: Final = {
    name: (role, rank) for role, names in _HEADER_NAMES.items() for rank, name in enumerate(names)
}
_FALLBACK_RANK: Final = len(_NAME_RANKS)
"""Rank of a name that only contains a role word ("Date of purchase"): after every exact name."""
_FALLBACK_WORDS: Final = (
    ("balance", _Role.BALANCE),
    ("date", _Role.DATE),
    ("amount", _Role.AMOUNT),
    ("description", _Role.DESCRIPTION),
)
_CURRENCY_WORDS: Final = frozenset(
    {"cad", "usd", "eur", "gbp", "aud", "nzd", "chf", "jpy", "inr", "mxn", "hkd", "sgd"}
)
_NOT_ALPHANUMERIC: Final = re.compile(r"[^0-9a-z]+")
_ROLE_LABELS: Final = {
    _Role.DATE: "date",
    _Role.DESCRIPTION: "description",
    _Role.AMOUNT: "amount",
}


def detect_csv(data: bytes) -> CsvDetection:
    """Guess how a CSV statement is laid out, and list what the user must still decide.

    Raises:
        StatementParseError: if the file breaks a size limit, isn't CSV text, or has no rows that
            could be transactions.
    """
    text, encoding = decode_detected(data)
    delimiter = _detect_delimiter(text)

    head = list(
        itertools.islice(iter_rows(text, delimiter), _HEADER_SEARCH_ROWS + _GUESS_SAMPLE_ROWS)
    )
    skip_rows, header = _find_header([cells for _, cells in head])
    header_key = None if header is None else normalize_header(header)
    first_data_index = skip_rows + (0 if header is None else 1)
    sample = [cells for _, cells in head[first_data_index:] if _is_candidate_row(cells, header_key)]
    if not sample:
        raise StatementParseError("No transactions were found in the file.")

    width = max(len(cells) for cells in [*([] if header is None else [header]), *sample])
    columns = tuple(_column_names(header, width))
    guess = _Guess(columns=columns, has_header=header is not None)
    guess.assign_columns(header, sample, width)

    checked = sorted({c for c in (guess.date_column,) if c is not None} | guess.amount_columns())
    values = _collect_values(text, delimiter, first_data_index, header_key, checked)
    guess.choose_date_format(values)
    guess.choose_amount_format(values)

    draft = CsvLayoutDraft(
        encoding=encoding,
        delimiter=delimiter,
        skip_rows=skip_rows,
        has_header=header is not None,
        date_column=guess.date_column,
        description_column=guess.description_column,
        amount=guess.amount,
        date_format=guess.date_format,
        decimal_separator=guess.decimal_separator,
        invert_signs=guess.invert_signs,
    )
    questions = guess.questions()
    preview: tuple[RawTransaction, ...] = ()
    layout = draft.to_layout()
    if layout is not None:
        preview, problem = _preview(text, layout)
        if problem is not None:
            questions.append(CsvQuestion(CsvQuestionKind.ROW_UNREADABLE, problem))

    return CsvDetection(
        layout=draft,
        header_signature=None if header is None else header_signature(header),
        columns=columns,
        preview=preview,
        questions=tuple(questions),
    )


def header_signature(header: Sequence[str]) -> str:
    """A stable key for a header row: the same for the same column names, whatever their case
    or spacing, and different whenever a column is added, removed, renamed or moved."""
    payload = json.dumps(normalize_header(header), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(_SIGNATURE_PREFIX + payload.encode("utf-8")).hexdigest()


class _Guess:
    """The layout decisions made so far, and the questions they leave open."""

    def __init__(self, columns: tuple[str, ...], *, has_header: bool) -> None:
        self.columns = columns
        self.has_header = has_header
        self.date_column: int | None = None
        self.description_column: int | None = None
        self.amount: AmountColumns | None = None
        self.date_format: str | None = None
        self.decimal_separator: DecimalSeparator = "."
        self.invert_signs: bool | None = None
        self._guessed_roles: list[_Role] = []
        self._half_amount: _Role | None = None
        self._format_questions: list[CsvQuestion] = []
        self._amount_unreadable = False

    def amount_columns(self) -> set[int]:
        return set() if self.amount is None else set(self.amount.columns)

    def assign_columns(self, header: list[str] | None, sample: list[list[str]], width: int) -> None:
        named = _roles_from_header(header) if header is not None else {}
        taken = set(named.values())

        self.date_column = named.get(_Role.DATE)
        if self.date_column is None:
            self.date_column = _guess_date_column(sample, width, taken)
            if self.date_column is not None:
                taken.add(self.date_column)
                self._guessed_roles.append(_Role.DATE)

        signed, debit, credit = (named.get(r) for r in (_Role.AMOUNT, _Role.DEBIT, _Role.CREDIT))
        if signed is not None:
            self.amount = SignedAmount(signed)
        elif debit is not None and credit is not None:
            self.amount = DebitCredit(debit, credit)
        elif debit is not None or credit is not None:
            self._half_amount = _Role.DEBIT if debit is not None else _Role.CREDIT
        else:
            self.amount = _guess_amount(sample, width, taken)
            if self.amount is not None:
                taken.update(self.amount.columns)
                self._guessed_roles.append(_Role.AMOUNT)

        self.description_column = named.get(_Role.DESCRIPTION)
        if self.description_column is None:
            self.description_column = _guess_description_column(sample, width, taken)
            if self.description_column is not None:
                self._guessed_roles.append(_Role.DESCRIPTION)

    def choose_date_format(self, values: dict[int, list[str]]) -> None:
        if self.date_column is None:
            return
        dates = values[self.date_column]
        name = quote(self.columns[self.date_column])
        if not dates:
            self._ask(CsvQuestionKind.DATE_FORMAT_UNKNOWN, f"The {name} column has no dates in it.")
            return
        formats = _fitting_date_formats(dates)
        if not formats:
            unreadable = next((d for d in dates if not _looks_like_date(d)), None)
            self._ask(
                CsvQuestionKind.DATE_FORMAT_UNKNOWN,
                f"The dates in the {name} column aren't all written the same way, so Monelyth "
                "can't tell which format to use."
                if unreadable is None
                else f"The dates in the {name} column, such as {quote(unreadable)}, aren't in a "
                "format Monelyth can read. Choose the column that holds the dates.",
            )
            return

        # Formats that read every date identically (e.g. day-first and month-first when each
        # day equals its month) are one answer, so only the first of them is kept.
        readings: dict[str, list[datetime.date | None]] = {}
        for code in formats:
            reading = [match_date(d, code) for d in dates]
            if reading not in readings.values():
                readings[code] = reading
        if len(readings) == 1:
            self.date_format = formats[0]
            return
        ranked = sorted(readings, key=lambda code: _order_breaks(readings[code]))
        first, second = readings[ranked[0]], readings[ranked[1]]
        example = next(d for d, a, b in zip(dates, first, second, strict=True) if a != b)
        labels = _join_or([date_format_label(code) for code in ranked])
        self._ask(
            CsvQuestionKind.DATE_ORDER_AMBIGUOUS,
            f"Dates such as {quote(example)} could be read as {labels}. Which does your bank use?",
            tuple(ranked),
        )

    def choose_amount_format(self, values: dict[int, list[str]]) -> None:
        if self.amount is None:
            return
        amounts = [value for column in self.amount.columns for value in values[column]]
        separators: list[DecimalSeparator] = [
            sep for sep in DECIMAL_SEPARATORS if _all_amounts_read(amounts, sep)
        ]
        if not separators:
            names = _join_and([quote(self.columns[c]) for c in self.amount.columns])
            example = next(a for a in amounts if not _reads_as_amount(a, "."))
            self._ask(
                CsvQuestionKind.AMOUNT_FORMAT_UNKNOWN,
                f"Some values in {names}, such as {quote(example)}, aren't amounts Monelyth can "
                "read. Choose the column that holds the amounts.",
            )
            self.amount = None
            self._amount_unreadable = True
            if _Role.AMOUNT in self._guessed_roles:
                self._guessed_roles.remove(_Role.AMOUNT)
            return

        # Both separators read every value only when none has cents ("12", "1 234", "12,500").
        # A decimal point is then the far more common convention.
        self.decimal_separator = separators[0]
        if isinstance(self.amount, DebitCredit):
            self.invert_signs = False
            return
        if any(has_credit_debit_marker(a) for a in amounts):
            self.invert_signs = False
            return

        cents = [parse_amount(a, self.decimal_separator) for a in amounts]
        negatives = sum(1 for c in cents if c is not None and c < 0)
        positives = sum(1 for c in cents if c is not None and c > 0)
        # A bank account mostly spends; a card statement that shows purchases as positive is
        # mostly positive. Only the first is safe to assume.
        if positives <= negatives:
            self.invert_signs = False
            return
        self._ask(
            CsvQuestionKind.SIGN_CONVENTION_UNKNOWN,
            "Every amount in this file is positive, so Monelyth can't tell spending from money "
            "coming in. Are purchases shown as positive numbers? Credit card statements often "
            "do this."
            if negatives == 0
            else "Most amounts in this file are positive. Credit card statements often show "
            "purchases as positive numbers and payments as negative ones. Is that the case here?",
        )

    def questions(self) -> list[CsvQuestion]:
        questions: list[CsvQuestion] = []
        if self._guessed_roles:
            questions.append(CsvQuestion(CsvQuestionKind.COLUMNS_GUESSED, self._guessed_message()))
        if self.date_column is None:
            questions.append(
                CsvQuestion(
                    CsvQuestionKind.NO_DATE_COLUMN,
                    "Monelyth couldn't find the date column. Choose the column that holds each "
                    "transaction's date.",
                )
            )
        if self.description_column is None:
            questions.append(
                CsvQuestion(
                    CsvQuestionKind.NO_DESCRIPTION_COLUMN,
                    "Monelyth couldn't find the description column. Choose the column that names "
                    "the merchant or describes each transaction.",
                )
            )
        if self.amount is None and not self._amount_unreadable:
            questions.append(CsvQuestion(CsvQuestionKind.NO_AMOUNT_COLUMN, self._amount_message()))
        questions.extend(self._format_questions)
        return questions

    def _ask(self, kind: CsvQuestionKind, message: str, options: tuple[str, ...] = ()) -> None:
        self._format_questions.append(CsvQuestion(kind, message, options))

    def _guessed_message(self) -> str:
        if not self.has_header:
            return (
                "This file has no header row, so Monelyth guessed which column is which from "
                "the data. Check the date, description and amount columns."
            )
        roles = _join_and([_ROLE_LABELS[role] for role in self._guessed_roles])
        if len(self._guessed_roles) == 1:
            return (
                f"The header doesn't name the {roles} column, so Monelyth guessed it from the "
                "data. Check that it's right."
            )
        return (
            f"The header doesn't name the {roles} columns, so Monelyth guessed them from the "
            "data. Check that they're right."
        )

    def _amount_message(self) -> str:
        if self._half_amount is _Role.DEBIT:
            return (
                "Monelyth found a column for money out but none for money in. Choose the column "
                "for money in, or a single amount column."
            )
        if self._half_amount is _Role.CREDIT:
            return (
                "Monelyth found a column for money in but none for money out. Choose the column "
                "for money out, or a single amount column."
            )
        return (
            "Monelyth couldn't find the amount column. Choose the column with the amounts, or "
            "the separate columns for money out and money in."
        )


def _detect_delimiter(text: str) -> Delimiter:
    """Pick the delimiter that splits the most rows into the same number of cells.

    ``csv.Sniffer`` alone gets real statements wrong: it prefers a comma in a semicolon file
    whose amounts use decimal commas, and preamble lines confuse it. So each delimiter is scored
    by how consistently it splits the opening rows, and Sniffer only breaks ties.
    """
    sample = text[:_DELIMITER_SAMPLE_CHARS]
    scores = {delimiter: _consistency(sample, delimiter) for delimiter in DELIMITERS}
    best = max(scores.values())
    tied: list[Delimiter] = [d for d in DELIMITERS if scores[d] == best]
    if len(tied) == 1:
        return tied[0]
    try:
        sniffed = csv.Sniffer().sniff(sample[:_SNIFF_SAMPLE_CHARS], delimiters="".join(tied))
    except csv.Error:
        return tied[0]
    for delimiter in tied:
        if delimiter == sniffed.delimiter:
            return delimiter
    return tied[0]


def _consistency(sample: str, delimiter: Delimiter) -> tuple[int, int]:
    """``(rows sharing the most common width, that width)``, counting rows of 2+ cells."""
    reader = csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter)
    widths: Counter[int] = Counter()
    try:
        for cells in itertools.islice(reader, _DELIMITER_SAMPLE_ROWS):
            if len(cells) >= 2:
                widths[len(cells)] += 1
    except csv.Error:
        pass  # The sample may end inside a quoted value; the rows read so far still count.
    if not widths:
        return (0, 0)
    width, count = max(widths.items(), key=lambda item: (item[1], item[0]))
    return (count, width)


def _find_header(rows: list[list[str]]) -> tuple[int, list[str] | None]:
    """Return ``(rows above the header or first transaction, the header or None)``."""
    window = rows[:_HEADER_SEARCH_ROWS]
    for index, cells in enumerate(window):
        if _is_named_header(cells):
            return index, cells

    widths = Counter(len(cells) for cells in window if len(cells) >= 2)
    table_width = max(widths.items(), key=lambda item: (item[1], item[0]))[0] if widths else 0
    start = next(
        (
            index
            for index, cells in enumerate(window)
            if len(cells) == table_width and any(_looks_like_date(cell) for cell in cells)
        ),
        0,
    )
    # A row of unfamiliar names ("Datum", "Text", "Summe") right above the data is still a
    # header: it has the table's width and holds no dates or numbers.
    if start > 0 and len(rows[start - 1]) == table_width and _is_text_row(rows[start - 1]):
        return start - 1, rows[start - 1]
    return start, None


def _is_named_header(cells: list[str]) -> bool:
    roles = {found[0] for cell in cells if (found := _role_of(cell)) is not None}
    return len(roles) >= 2 and _is_text_row(cells)


def _is_text_row(cells: list[str]) -> bool:
    values = [cell for cell in cells if not is_blank(cell)]
    return len(values) >= 2 and not any(_looks_like_value(value) for value in values)


def _is_candidate_row(cells: list[str], header_key: tuple[str, ...] | None) -> bool:
    """Whether a row below the header could be a transaction, for guessing purposes."""
    values = [cell for cell in cells if not is_blank(cell)]
    if len(values) < 2:
        return False
    if header_key is not None and repeats_header(cells, header_key):
        return False
    has_label = any(is_summary_label(value) for value in values)
    return not has_label or any(_looks_like_date(value) for value in values)


def _column_names(header: list[str] | None, width: int) -> list[str]:
    names: list[str] = []
    for index in range(width):
        name = (
            clean_description(header[index]) if header is not None and index < len(header) else ""
        )
        names.append(name or f"Column {index + 1}")
    return names


def _normalize_name(cell: str) -> str:
    """``"Débit (CAD)"`` -> ``"debit"``: no accents, case, punctuation or currency code."""
    decomposed = unicodedata.normalize("NFKD", cell)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()
    words = _NOT_ALPHANUMERIC.sub(" ", plain).split()
    if len(words) > 1 and words[-1] in _CURRENCY_WORDS:
        words.pop()
        if len(words) > 1 and words[-1] == "in":
            words.pop()
    return " ".join(words)


def _role_of(cell: str) -> tuple[_Role, int] | None:
    name = _normalize_name(cell)
    if (known := _NAME_RANKS.get(name)) is not None:
        return known
    words = name.split()
    for word, role in _FALLBACK_WORDS:
        if word in words:
            return role, _FALLBACK_RANK
    return None


def _roles_from_header(header: list[str]) -> dict[_Role, int]:
    """The best-ranked column for each role named in the header; the leftmost wins a tie."""
    best: dict[_Role, tuple[int, int]] = {}
    for column, cell in enumerate(header):
        found = _role_of(cell)
        if found is None:
            continue
        role, rank = found
        if role not in best or rank < best[role][0]:
            best[role] = (rank, column)
    return {role: column for role, (_, column) in best.items()}


def _sample_values(sample: list[list[str]], column: int) -> list[str]:
    return [
        cells[column].strip()
        for cells in sample
        if column < len(cells) and not is_blank(cells[column])
    ]


def _is_filled(values: list[str], sample: list[list[str]]) -> bool:
    return len(values) >= _MIN_FILL * len(sample)


def _guess_date_column(sample: list[list[str]], width: int, taken: set[int]) -> int | None:
    for column in range(width):
        if column in taken:
            continue
        values = _sample_values(sample, column)
        if values and _is_filled(values, sample) and _fitting_date_formats(values):
            return column
    return None


def _guess_amount(sample: list[list[str]], width: int, taken: set[int]) -> AmountColumns | None:
    """Find a debit/credit pair or a signed amount among the columns that hold only numbers.

    A pair is two neighbouring number columns that are each sometimes blank while every row
    fills at least one of them. A balance column is always filled, so on its own it reads as a
    signed amount; that is why a guessed amount always comes with a question.
    """
    numeric = [
        column
        for column in range(width)
        if column not in taken and _is_numeric(_sample_values(sample, column))
    ]
    for debit, credit in itertools.pairwise(numeric):
        if credit != debit + 1:
            continue
        debit_values, credit_values = _sample_values(sample, debit), _sample_values(sample, credit)
        sometimes_blank = len(debit_values) < len(sample) and len(credit_values) < len(sample)
        always_one = all(
            not is_blank(cell_at(cells, debit)) or not is_blank(cell_at(cells, credit))
            for cells in sample
        )
        if sometimes_blank and always_one:
            return DebitCredit(debit, credit)
    for column in numeric:
        if _is_filled(_sample_values(sample, column), sample):
            return SignedAmount(column)
    return None


def _guess_description_column(sample: list[list[str]], width: int, taken: set[int]) -> int | None:
    """The text column with the most distinct values, then the most text: the merchant names."""
    best: tuple[int, int, int] | None = None
    best_column: int | None = None
    for column in range(width):
        if column in taken:
            continue
        values = _sample_values(sample, column)
        if not values or _is_numeric(values) or _fitting_date_formats(values):
            continue
        score = (len(set(values)), sum(len(value) for value in values), -column)
        if best is None or score > best:
            best, best_column = score, column
    return best_column


def _collect_values(
    text: str,
    delimiter: Delimiter,
    first_data_index: int,
    header_key: tuple[str, ...] | None,
    columns: Iterable[int],
) -> dict[int, list[str]]:
    """Every non-blank value in ``columns``, from every row that could be a transaction."""
    values: dict[int, list[str]] = {column: [] for column in columns}
    for row_number, cells in iter_rows(text, delimiter):
        if row_number <= first_data_index or not _is_candidate_row(cells, header_key):
            continue
        for column, column_values in values.items():
            if column < len(cells) and not is_blank(cells[column]):
                column_values.append(cells[column].strip())
    return values


def _preview(text: str, layout: CsvLayout) -> tuple[tuple[RawTransaction, ...], str | None]:
    """The first transactions, plus the problem (if any) that stops the layout reading every row."""
    preview: list[RawTransaction] = []
    found = False
    try:
        for outcome in iter_transactions(text, layout):
            if isinstance(outcome, RawTransaction):
                found = True
                if len(preview) < PREVIEW_ROWS:
                    preview.append(outcome)
    except StatementParseError as error:
        return tuple(preview), str(error)
    if not found:
        return (), "No transactions were found with this layout."
    return tuple(preview), None


def _fitting_date_formats(values: list[str]) -> list[str]:
    return [code for code in DATE_FORMATS if all(match_date(value, code) for value in values)]


def _order_breaks(dates: Sequence[datetime.date | None]) -> int:
    """How often consecutive dates break the file's overall order. Statements are sorted, so
    the right reading of an ambiguous date format has fewer breaks."""
    known = [date for date in dates if date is not None]
    pairs = list(itertools.pairwise(known))
    rising = sum(1 for earlier, later in pairs if later < earlier)
    falling = sum(1 for earlier, later in pairs if later > earlier)
    return min(rising, falling)


def _looks_like_date(text: str) -> bool:
    return any(match_date(text, code) for code in DATE_FORMATS)


def _looks_like_value(text: str) -> bool:
    return _looks_like_date(text) or any(_reads_as_amount(text, s) for s in DECIMAL_SEPARATORS)


def _reads_as_amount(text: str, separator: DecimalSeparator) -> bool:
    try:
        return parse_amount(text, separator) is not None
    except CsvValueError:
        return False


def _all_amounts_read(values: list[str], separator: DecimalSeparator) -> bool:
    return all(_reads_as_amount(value, separator) for value in values)


def _is_numeric(values: list[str]) -> bool:
    return bool(values) and any(_all_amounts_read(values, s) for s in DECIMAL_SEPARATORS)


def _join_and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _join_or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"
