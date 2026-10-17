"""Checks on ``scripts/generate_sample_data.py`` and the files it committed in ``sample-data/``."""

from __future__ import annotations

import csv
import datetime
import itertools
import subprocess
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from monelyth_engine.ingest.ofx_statement import parse_ofx

ENGINE_DIR: Final = Path(__file__).resolve().parents[1]
SCRIPT: Final = ENGINE_DIR / "scripts" / "generate_sample_data.py"
COMMITTED_DIR: Final = ENGINE_DIR.parent / "sample-data"
GENERATED_FILES: Final = (
    "demo-checking.csv",
    "demo-credit-card.csv",
    "demo-checking.ofx",
    "labels.csv",
)

# Copied from PLAN.md step 1.1 on purpose: the generator must match the plan, not itself.
DEFAULT_CATEGORIES: Final = frozenset(
    {
        "Salary",
        "Other Income",
        "Rent/Mortgage",
        "Utilities",
        "Groceries",
        "Dining Out",
        "Coffee",
        "Transport",
        "Gas",
        "Rideshare",
        "Shopping",
        "Subscriptions",
        "Entertainment",
        "Health",
        "Education",
        "Travel",
        "Fees & Interest",
        "Gifts & Donations",
        "Transfers",
        "Other",
    }
)

type Label = tuple[str, datetime.date, str, int, str]
"""account, posted date, description, amount in cents, category."""


def _generate(output_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(output_dir), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_dir = tmp_path_factory.mktemp("sample-data")
    result = _generate(output_dir)
    assert result.returncode == 0, result.stderr
    return output_dir


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _cents(text: str) -> int:
    cents = Decimal(text) * 100
    assert cents == cents.to_integral_value(), f"{text!r} is not whole cents"
    return int(cents)


def _us_date(text: str) -> datetime.date:
    return datetime.datetime.strptime(text, "%m/%d/%Y").date()


def _checking(directory: Path) -> list[tuple[datetime.date, str, int]]:
    return [
        (datetime.date.fromisoformat(row["Date"]), row["Description"], _cents(row["Amount"]))
        for row in _rows(directory / "demo-checking.csv")
    ]


def _card(directory: Path) -> list[tuple[datetime.date, datetime.date, str, int]]:
    """(transaction date, posted date, description, signed cents) for each card row."""
    card: list[tuple[datetime.date, datetime.date, str, int]] = []
    for row in _rows(directory / "demo-credit-card.csv"):
        debit, credit = row["Debit"], row["Credit"]
        assert bool(debit) != bool(credit), f"exactly one of Debit/Credit must be set: {row}"
        amount = -_cents(debit) if debit else _cents(credit)
        card.append(
            (
                _us_date(row["Transaction Date"]),
                _us_date(row["Posted Date"]),
                row["Description"],
                amount,
            )
        )
    return card


def _labels(directory: Path) -> list[Label]:
    return [
        (
            row["account"],
            datetime.date.fromisoformat(row["date"]),
            row["description"],
            int(row["amount_cents"]),
            row["category"],
        )
        for row in _rows(directory / "labels.csv")
    ]


# --- Reproducibility ---------------------------------------------------------------------


def test_generator_is_deterministic(generated: Path, tmp_path: Path) -> None:
    result = _generate(tmp_path)

    assert result.returncode == 0, result.stderr
    for name in GENERATED_FILES:
        assert (tmp_path / name).read_bytes() == (generated / name).read_bytes(), name
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(GENERATED_FILES)


def test_committed_files_match_the_generator(generated: Path) -> None:
    """Fails when the generator changed but sample-data/ was not regenerated."""
    for name in GENERATED_FILES:
        assert (COMMITTED_DIR / name).read_bytes() == (generated / name).read_bytes(), (
            f"sample-data/{name} is out of date; run scripts/generate_sample_data.py"
        )


def test_files_use_lf_line_endings(generated: Path) -> None:
    for name in GENERATED_FILES:
        assert b"\r" not in (generated / name).read_bytes(), name


def test_period_is_the_twelve_months_ending_at_end_month(tmp_path: Path) -> None:
    result = _generate(tmp_path, "--end-month", "2025-02")

    assert result.returncode == 0, result.stderr
    dates = [label[1] for label in _labels(tmp_path)]
    assert min(dates) >= datetime.date(2024, 3, 1)
    assert max(dates) <= datetime.date(2025, 2, 28)
    assert {(d.year, d.month) for d in dates} == {(2024, month) for month in range(3, 13)} | {
        (2025, 1),
        (2025, 2),
    }


@pytest.mark.parametrize("end_month", ["2026-13", "2026-9-1", "September", ""])
def test_invalid_end_month_is_rejected(end_month: str, tmp_path: Path) -> None:
    result = _generate(tmp_path, "--end-month", end_month)

    assert result.returncode == 2
    assert "expected YYYY-MM" in result.stderr
    assert not any(tmp_path.iterdir())


# --- File formats ------------------------------------------------------------------------


def test_csv_headers(generated: Path) -> None:
    first_lines = {
        name: (generated / name).read_text(encoding="utf-8").split("\n", 1)[0]
        for name in ("demo-checking.csv", "demo-credit-card.csv", "labels.csv")
    }

    assert first_lines == {
        "demo-checking.csv": "Date,Description,Amount",
        "demo-credit-card.csv": "Transaction Date,Posted Date,Description,Debit,Credit",
        "labels.csv": "account,date,description,amount_cents,category",
    }


def test_credit_card_rows_post_on_or_after_the_purchase(generated: Path) -> None:
    for transacted, posted, description, _ in _card(generated):
        assert datetime.timedelta(0) <= posted - transacted <= datetime.timedelta(days=3), (
            description
        )


def test_amounts_have_two_decimals(generated: Path) -> None:
    checking = [row["Amount"] for row in _rows(generated / "demo-checking.csv")]
    card = [
        value
        for row in _rows(generated / "demo-credit-card.csv")
        for value in (row["Debit"], row["Credit"])
        if value
    ]

    for text in checking + card:
        assert text.lstrip("-").partition(".")[2].isdigit(), text
        assert len(text.partition(".")[2]) == 2, text
    assert all(not text.startswith("-") for text in card), "card columns hold positive numbers"


def test_ofx_parses_and_matches_the_checking_csv(generated: Path) -> None:
    statement = parse_ofx((generated / "demo-checking.ofx").read_bytes())

    assert statement.currency == "CAD"
    assert statement.warnings == ()
    parsed = [(t.posted_date, t.description, t.amount_cents) for t in statement.transactions]
    assert parsed == _checking(generated)
    fitids = [t.external_id for t in statement.transactions]
    assert None not in fitids
    assert len(set(fitids)) == len(fitids)


# --- Labels ------------------------------------------------------------------------------


def test_label_categories_are_exactly_the_defaults(generated: Path) -> None:
    used = {label[4] for label in _labels(generated)}

    assert used <= DEFAULT_CATEGORIES
    # Every category appears, so the demo data exercises all of them.
    assert used == DEFAULT_CATEGORIES


def test_labels_match_every_csv_row(generated: Path) -> None:
    labels = _labels(generated)
    checking = _checking(generated)
    card = _card(generated)

    assert len(labels) == len(checking) + len(card)
    assert [
        (day, text, cents) for account, day, text, cents, _ in labels if account == "checking"
    ] == checking
    assert [
        (day, text, cents) for account, day, text, cents, _ in labels if account == "credit_card"
    ] == [(posted, text, cents) for _, posted, text, cents in card]
    assert {label[0] for label in labels} == {"checking", "credit_card"}


def test_transfers_pair_up_between_the_accounts(generated: Path) -> None:
    labels = _labels(generated)
    out_of_checking = [
        label for label in labels if label[0] == "checking" and label[4] == "Transfers"
    ]
    into_card = [label for label in labels if label[0] == "credit_card" and label[4] == "Transfers"]

    assert len(out_of_checking) == len(into_card) == 11
    for sent, received in zip(out_of_checking, into_card, strict=True):
        assert sent[3] < 0
        assert received[3] == -sent[3]
        assert 1 <= (received[1] - sent[1]).days <= 3


def test_card_payment_covers_the_previous_month(generated: Path) -> None:
    labels = [label for label in _labels(generated) if label[0] == "credit_card"]
    for payment in (label for label in labels if label[4] == "Transfers"):
        previous = (payment[1].replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
        spent = -sum(
            label[3]
            for label in labels
            if label[4] != "Transfers" and label[1].replace(day=1) == previous
        )
        assert payment[3] == spent


# --- Patterns the later phases rely on ---------------------------------------------------


def test_identical_coffees_on_the_same_day_are_both_kept(generated: Path) -> None:
    counts = Counter(label for label in _labels(generated) if label[4] == "Coffee")

    pairs = [label for label, count in counts.items() if count == 2]
    assert len(pairs) >= 3
    assert all(count <= 2 for count in counts.values())


def test_salary_is_paid_every_two_weeks(generated: Path) -> None:
    salary = [label for label in _labels(generated) if label[4] == "Salary"]

    assert len(salary) == 26
    assert {label[2] for label in salary} == {"PAYROLL ACME CORP"}
    assert len({label[3] for label in salary}) == 1
    gaps = {(b[1] - a[1]).days for a, b in itertools.pairwise(salary)}
    assert gaps == {14}


def test_rent_is_paid_on_the_first_of_each_month(generated: Path) -> None:
    rent = [label for label in _labels(generated) if label[4] == "Rent/Mortgage"]

    assert len(rent) == 12
    assert {label[1].day for label in rent} == {1}


def test_subscription_price_increases_once(generated: Path) -> None:
    netflix = [label[3] for label in _labels(generated) if label[2].startswith("NETFLIX.COM")]

    assert len(netflix) == 12
    changes = [(a, b) for a, b in itertools.pairwise(netflix) if a != b]
    assert changes == [(-1899, -2099)]
