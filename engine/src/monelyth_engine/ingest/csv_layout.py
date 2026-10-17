"""How a bank lays out its CSV statements, and how that layout is saved.

A confirmed :class:`CsvLayout` is stored as JSON in the ``csv_profiles`` table, keyed by the
statement's header signature, so the next import from the same bank needs no questions. Stored
JSON is untrusted on the way back in (the database file belongs to the user and can be edited),
so :meth:`CsvLayout.from_dict` checks every field instead of trusting it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, cast

from monelyth_engine.ingest.csv_values import DATE_FORMATS, DECIMAL_SEPARATORS, DecimalSeparator

Encoding = Literal["utf-8-sig", "cp1252"]
Delimiter = Literal[",", ";", "\t"]

ENCODINGS: Final[tuple[Encoding, ...]] = ("utf-8-sig", "cp1252")
"""``utf-8-sig`` reads UTF-8 with or without Excel's byte-order mark; ``cp1252`` is the
"ANSI" encoding older Windows software exports."""
DELIMITERS: Final[tuple[Delimiter, ...]] = (",", ";", "\t")

MAX_COLUMNS: Final = 64
"""Widest row accepted. Real statements have about 4 to 15 columns."""
MAX_SKIP_ROWS: Final = 100
"""Most rows a layout may skip above the header (account number, date range, notes)."""
LAYOUT_VERSION: Final = 1
"""Bumped when the saved form changes, so old profiles can be recognised and migrated."""

_MAX_LISTED_CHOICES: Final = 4

_LAYOUT_KEYS: Final = frozenset(
    {
        "version",
        "encoding",
        "delimiter",
        "skip_rows",
        "has_header",
        "date_column",
        "description_column",
        "amount",
        "date_format",
        "decimal_separator",
        "invert_signs",
    }
)


class CsvLayoutError(ValueError):
    """A layout is inconsistent, or saved layout data is missing, malformed or tampered with."""


@dataclass(frozen=True, slots=True)
class SignedAmount:
    """One column holds every amount, negative for money out (unless the layout inverts it)."""

    column: int

    def __post_init__(self) -> None:
        _check_column("column", self.column)

    @property
    def columns(self) -> tuple[int, ...]:
        return (self.column,)


@dataclass(frozen=True, slots=True)
class DebitCredit:
    """Money out and money in sit in separate columns, usually with one of them blank.

    Each amount counts by its size: a debit always takes money out and a credit always puts it
    in, whether or not the bank writes a minus sign in the debit column. A row with both filled
    nets them.
    """

    debit_column: int
    credit_column: int

    def __post_init__(self) -> None:
        _check_column("debit_column", self.debit_column)
        _check_column("credit_column", self.credit_column)
        if self.debit_column == self.credit_column:
            raise CsvLayoutError("the debit and credit columns must be different")

    @property
    def columns(self) -> tuple[int, ...]:
        return (self.debit_column, self.credit_column)


AmountColumns = SignedAmount | DebitCredit


@dataclass(frozen=True, slots=True)
class CsvLayout:
    """Everything :func:`~monelyth_engine.ingest.csv_statement.parse_csv` needs to read a file.

    Rows are CSV records counted from 0, so a quoted value with a line break inside is one row,
    the same way a spreadsheet shows it. Column numbers also count from 0.
    """

    encoding: Encoding
    delimiter: Delimiter
    skip_rows: int
    """Rows above the header (or above the first transaction, if there is no header)."""
    has_header: bool
    date_column: int
    description_column: int
    amount: AmountColumns
    date_format: str
    """One of :data:`~monelyth_engine.ingest.csv_values.DATE_FORMATS`."""
    decimal_separator: DecimalSeparator
    invert_signs: bool
    """``True`` for statements that show purchases as positive (common on credit cards)."""

    def __post_init__(self) -> None:
        _check_common(self.encoding, self.delimiter, self.skip_rows, self.decimal_separator)
        _check_distinct_columns(self.date_column, self.description_column, self.amount)
        if self.date_format not in DATE_FORMATS:
            raise CsvLayoutError(f"unsupported date format {self.date_format!r}")

    @property
    def columns(self) -> tuple[int, ...]:
        """Every column the layout reads."""
        return (self.date_column, self.description_column, *self.amount.columns)

    def to_dict(self) -> dict[str, object]:
        """A JSON-ready form that :meth:`from_dict` reads back."""
        return {
            "version": LAYOUT_VERSION,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "skip_rows": self.skip_rows,
            "has_header": self.has_header,
            "date_column": self.date_column,
            "description_column": self.description_column,
            "amount": _amount_to_dict(self.amount),
            "date_format": self.date_format,
            "decimal_separator": self.decimal_separator,
            "invert_signs": self.invert_signs,
        }

    @classmethod
    def from_dict(cls, data: object) -> CsvLayout:
        """Rebuild a layout from :meth:`to_dict` output, typically just loaded from JSON.

        Raises:
            CsvLayoutError: if ``data`` is not exactly a valid saved layout: a key is missing or
                unknown, a value has the wrong type or is out of range, or the columns clash.
        """
        fields = _as_mapping(data, "layout", _LAYOUT_KEYS)
        version = fields["version"]
        if type(version) is not int or version != LAYOUT_VERSION:
            raise CsvLayoutError(f"unsupported layout version {version!r}")
        return cls(
            encoding=_choice(fields, "encoding", ENCODINGS),
            delimiter=_choice(fields, "delimiter", DELIMITERS),
            skip_rows=_integer(fields, "skip_rows", MAX_SKIP_ROWS),
            has_header=_boolean(fields, "has_header"),
            date_column=_integer(fields, "date_column", MAX_COLUMNS - 1),
            description_column=_integer(fields, "description_column", MAX_COLUMNS - 1),
            amount=_amount_from_dict(fields["amount"]),
            date_format=_choice(fields, "date_format", DATE_FORMATS),
            decimal_separator=_choice(fields, "decimal_separator", DECIMAL_SEPARATORS),
            invert_signs=_boolean(fields, "invert_signs"),
        )


@dataclass(frozen=True, slots=True)
class CsvLayoutDraft:
    """Detection's best guess at a layout. ``None`` marks a part it couldn't decide.

    The file structure (encoding, delimiter, rows to skip, header) and the decimal separator are
    always decided; the columns, date format and sign convention may need the user's answer.
    """

    encoding: Encoding
    delimiter: Delimiter
    skip_rows: int
    has_header: bool
    date_column: int | None
    description_column: int | None
    amount: AmountColumns | None
    date_format: str | None
    decimal_separator: DecimalSeparator
    invert_signs: bool | None

    def __post_init__(self) -> None:
        _check_common(self.encoding, self.delimiter, self.skip_rows, self.decimal_separator)
        _check_distinct_columns(self.date_column, self.description_column, self.amount)
        if self.date_format is not None and self.date_format not in DATE_FORMATS:
            raise CsvLayoutError(f"unsupported date format {self.date_format!r}")

    def to_layout(self) -> CsvLayout | None:
        """The finished layout, or ``None`` while any part is still undecided."""
        if (
            self.date_column is None
            or self.description_column is None
            or self.amount is None
            or self.date_format is None
            or self.invert_signs is None
        ):
            return None
        return CsvLayout(
            encoding=self.encoding,
            delimiter=self.delimiter,
            skip_rows=self.skip_rows,
            has_header=self.has_header,
            date_column=self.date_column,
            description_column=self.description_column,
            amount=self.amount,
            date_format=self.date_format,
            decimal_separator=self.decimal_separator,
            invert_signs=self.invert_signs,
        )

    def to_dict(self) -> dict[str, object]:
        """The same shape as :meth:`CsvLayout.to_dict`, with ``None`` for undecided parts."""
        return {
            "version": LAYOUT_VERSION,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "skip_rows": self.skip_rows,
            "has_header": self.has_header,
            "date_column": self.date_column,
            "description_column": self.description_column,
            "amount": None if self.amount is None else _amount_to_dict(self.amount),
            "date_format": self.date_format,
            "decimal_separator": self.decimal_separator,
            "invert_signs": self.invert_signs,
        }


def _check_column(name: str, column: int) -> None:
    if not 0 <= column < MAX_COLUMNS:
        raise CsvLayoutError(f"{name} must be from 0 to {MAX_COLUMNS - 1}, got {column}")


def _check_common(
    encoding: Encoding, delimiter: Delimiter, skip_rows: int, decimal_separator: DecimalSeparator
) -> None:
    if encoding not in ENCODINGS:
        raise CsvLayoutError(f"unsupported encoding {encoding!r}")
    if delimiter not in DELIMITERS:
        raise CsvLayoutError(f"unsupported delimiter {delimiter!r}")
    if not 0 <= skip_rows <= MAX_SKIP_ROWS:
        raise CsvLayoutError(f"skip_rows must be from 0 to {MAX_SKIP_ROWS}, got {skip_rows}")
    if decimal_separator not in DECIMAL_SEPARATORS:
        raise CsvLayoutError(f"unsupported decimal separator {decimal_separator!r}")


def _check_distinct_columns(
    date_column: int | None, description_column: int | None, amount: AmountColumns | None
) -> None:
    if date_column is not None:
        _check_column("date_column", date_column)
    if description_column is not None:
        _check_column("description_column", description_column)
    used = [column for column in (date_column, description_column) if column is not None]
    if amount is not None:
        used.extend(amount.columns)
    if len(used) != len(set(used)):
        raise CsvLayoutError("the date, description and amount columns must all be different")


def _amount_to_dict(amount: AmountColumns) -> dict[str, object]:
    match amount:
        case SignedAmount(column=column):
            return {"kind": "signed", "column": column}
        case DebitCredit(debit_column=debit, credit_column=credit):
            return {"kind": "debit_credit", "debit_column": debit, "credit_column": credit}


def _amount_from_dict(data: object) -> AmountColumns:
    if not isinstance(data, Mapping):
        raise CsvLayoutError("'amount' must be an object")
    amount = cast("Mapping[object, object]", data)
    kind = amount.get("kind")
    if kind == "signed":
        fields = _as_mapping(amount, "amount", frozenset({"kind", "column"}))
        return SignedAmount(_integer(fields, "column", MAX_COLUMNS - 1))
    if kind == "debit_credit":
        fields = _as_mapping(amount, "amount", frozenset({"kind", "debit_column", "credit_column"}))
        return DebitCredit(
            debit_column=_integer(fields, "debit_column", MAX_COLUMNS - 1),
            credit_column=_integer(fields, "credit_column", MAX_COLUMNS - 1),
        )
    raise CsvLayoutError("'amount.kind' must be 'signed' or 'debit_credit'")


def _as_mapping(data: object, name: str, keys: frozenset[str]) -> Mapping[str, object]:
    """Check that ``data`` is an object with exactly ``keys``, so typos and extras are caught."""
    if not isinstance(data, Mapping):
        raise CsvLayoutError(f"{name!r} must be an object")
    fields = cast("Mapping[object, object]", data)
    # Keys come from untrusted JSON, so long ones are cut short in the message.
    unknown = sorted(repr(key)[:40] for key in fields if key not in keys)
    if unknown:
        raise CsvLayoutError(f"{name!r} has unknown keys: {', '.join(unknown[:5])}")
    missing = sorted(keys.difference(cast("Mapping[str, object]", fields)))
    if missing:
        raise CsvLayoutError(f"{name!r} is missing keys: {', '.join(missing)}")
    return cast("Mapping[str, object]", fields)


def _integer(fields: Mapping[str, object], key: str, maximum: int) -> int:
    value = fields[key]
    # bool is a subclass of int, so `true` must be rejected explicitly.
    if type(value) is not int or not 0 <= value <= maximum:
        raise CsvLayoutError(f"{key!r} must be a whole number from 0 to {maximum}")
    return value


def _boolean(fields: Mapping[str, object], key: str) -> bool:
    value = fields[key]
    if not isinstance(value, bool):
        raise CsvLayoutError(f"{key!r} must be true or false")
    return value


def _choice[T: str](fields: Mapping[str, object], key: str, choices: tuple[T, ...]) -> T:
    value = fields[key]
    for choice in choices:
        if value == choice and type(value) is str:
            return choice
    if len(choices) > _MAX_LISTED_CHOICES:
        raise CsvLayoutError(f"{key!r} is not a supported value")
    raise CsvLayoutError(f"{key!r} must be one of {', '.join(repr(c) for c in choices)}")
