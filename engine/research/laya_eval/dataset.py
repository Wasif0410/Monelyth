"""The labeled transactions, the ways of showing them to Laya, and the two baselines."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from monelyth_engine.demo.generator import Category
from monelyth_engine.normalize import normalize_merchant

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_LABELS: Final = REPO_ROOT / "sample-data" / "labels.csv"

CATEGORIES: Final = tuple(category.value for category in Category)
"""The seeded default categories, in the order the UI lists them."""

INSTRUCTIONS: Final = "Which budget category does this bank transaction belong to?"


@dataclass(frozen=True, slots=True)
class Example:
    description: str
    merchant: str
    amount_cents: int
    category: str


def load_examples(path: Path = DEFAULT_LABELS) -> list[Example]:
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    examples = [
        Example(
            description=row["description"],
            merchant=normalize_merchant(row["description"]),
            amount_cents=int(row["amount_cents"]),
            category=row["category"],
        )
        for row in rows
    ]
    unknown = {e.category for e in examples} - set(CATEGORIES)
    if unknown:
        raise ValueError(f"labels use categories that are not seeded defaults: {sorted(unknown)}")
    return examples


def first_per_merchant(examples: Sequence[Example]) -> list[int]:
    """Indices of the first example of each cleaned merchant: one vote per merchant.

    The classifier tier only ever sees merchants that memory and rules could not answer, so a
    merchant seen 47 times must not count 47 times when judging it.
    """
    seen: set[str] = set()
    keep: list[int] = []
    for index, example in enumerate(examples):
        if example.merchant not in seen:
            seen.add(example.merchant)
            keep.append(index)
    return keep


# --- State formats --------------------------------------------------------------------------


def _money(cents: int) -> str:
    return f"{abs(cents) / 100:.2f} CAD"


def _direction(cents: int) -> str:
    return "money out" if cents < 0 else "money in"


def state_text(example: Example) -> str:
    return (
        f"Merchant: {example.merchant}. Bank description: {example.description}. "
        f"Amount: {_money(example.amount_cents)} ({_direction(example.amount_cents)})."
    )


def state_json(example: Example) -> str:
    return json.dumps(
        {
            "merchant": example.merchant,
            "bank_description": example.description,
            "amount": _money(example.amount_cents),
            "direction": _direction(example.amount_cents),
        }
    )


def state_sentence(example: Example) -> str:
    verb = "paid" if example.amount_cents < 0 else "received"
    return f"I {verb} {_money(example.amount_cents)} - {example.merchant} ({example.description})"


def state_plain(example: Example) -> str:
    """No raw bank text at all: the sentence a person would say."""
    if example.amount_cents < 0:
        return f"Spent {_money(example.amount_cents)} at {example.merchant}."
    return f"Received {_money(example.amount_cents)} from {example.merchant}."


def state_merchant(example: Example) -> str:
    return example.merchant


STATE_FORMATS: Final[dict[str, Callable[[Example], str]]] = {
    "text": state_text,
    "json": state_json,
    "sentence": state_sentence,
    "plain": state_plain,
    "merchant": state_merchant,
}


# --- Criteria wordings ----------------------------------------------------------------------

DESCRIBED: Final[dict[str, str]] = {
    "Salary": "paycheque, payroll deposit",
    "Other Income": "refunds, money received from people",
    "Rent/Mortgage": "rent or mortgage payment",
    "Utilities": "electricity, gas bill, phone, internet",
    "Groceries": "supermarket, grocery store",
    "Dining Out": "restaurant, bar, takeout, food delivery",
    "Coffee": "coffee shop, cafe",
    "Transport": "public transit, parking",
    "Gas": "fuel station",
    "Rideshare": "Uber or Lyft ride, taxi",
    "Shopping": "retail, online shopping",
    "Subscriptions": "streaming, app or software subscription",
    "Entertainment": "movies, concerts, events",
    "Health": "pharmacy, doctor, dentist",
    "Education": "tuition, courses, books",
    "Travel": "flights, hotels",
    "Fees & Interest": "bank fees, interest charges",
    "Gifts & Donations": "charity, gifts, flowers",
    "Transfers": "card payment or transfer between own accounts",
    "Other": "ATM cash or anything else",
}

CRITERIA: Final[dict[str, dict[str, str | None]]] = {
    "names": dict.fromkeys(CATEGORIES),
    "described": {name: DESCRIBED[name] for name in CATEGORIES},
}


def question(criteria: str) -> dict[str, dict[str, object]]:
    return {
        "category": {
            "type": "choice",
            "instructions": INSTRUCTIONS,
            "criteria": CRITERIA[criteria],
        }
    }


# --- Baselines ------------------------------------------------------------------------------


def majority_class(examples: Sequence[Example]) -> str:
    return Counter(e.category for e in examples).most_common(1)[0][0]


# Two keyword tables, first match wins. GENERIC_KEYWORDS holds only words that name a kind of
# business or payment ("coffee", "pharmacy", "payment"): the trivial baseline. BRAND_KEYWORDS adds
# the brand names that appear in the sample data, so it is the shape of the default rules of
# PLAN.md 3.3 written by someone who has seen the data; it shows how far rules alone can go on
# this data set, not how a classifier compares on merchants nobody wrote a rule for.
GENERIC_KEYWORDS: Final[tuple[tuple[str, str], ...]] = (
    ("payroll", "Salary"),
    ("salary", "Salary"),
    ("refund", "Other Income"),
    ("transfer from", "Other Income"),
    ("property", "Rent/Mortgage"),
    ("rent", "Rent/Mortgage"),
    ("hydro", "Utilities"),
    ("wireless", "Utilities"),
    ("electric", "Utilities"),
    ("internet", "Utilities"),
    ("eats", "Dining Out"),
    ("restaurant", "Dining Out"),
    ("tavern", "Dining Out"),
    ("noodle", "Dining Out"),
    ("taco", "Dining Out"),
    ("pizza", "Dining Out"),
    ("grill", "Dining Out"),
    ("coffee", "Coffee"),
    ("cafe", "Coffee"),
    ("market", "Groceries"),
    ("grocer", "Groceries"),
    ("supermarket", "Groceries"),
    ("parking", "Transport"),
    ("transit", "Transport"),
    ("fuel", "Gas"),
    ("gas", "Gas"),
    ("taxi", "Rideshare"),
    ("subscription", "Subscriptions"),
    ("cinema", "Entertainment"),
    ("ticket", "Entertainment"),
    ("pharmacy", "Health"),
    ("drug", "Health"),
    ("dental", "Health"),
    ("clinic", "Health"),
    ("college", "Education"),
    ("university", "Education"),
    ("airline", "Travel"),
    ("hotel", "Travel"),
    ("fee", "Fees & Interest"),
    ("interest", "Fees & Interest"),
    ("donation", "Gifts & Donations"),
    ("florist", "Gifts & Donations"),
    ("food bank", "Gifts & Donations"),
    ("payment", "Transfers"),
    ("transfer", "Transfers"),
    ("atm", "Other"),
    ("withdrawal", "Other"),
)

BRAND_KEYWORDS: Final[tuple[tuple[str, str], ...]] = (
    ("eats", "Dining Out"),  # before "uber": Uber Eats is a meal, not a ride
    ("bell canada", "Utilities"),
    ("rogers", "Utilities"),
    ("lakeport gas", "Utilities"),
    ("mcdonald", "Dining Out"),
    ("starbucks", "Coffee"),
    ("tim hortons", "Coffee"),
    ("loblaws", "Groceries"),
    ("no frills", "Groceries"),
    ("farm boy", "Groceries"),
    ("presto", "Transport"),
    ("petro", "Gas"),
    ("shell", "Gas"),
    ("uber", "Rideshare"),
    ("lyft", "Rideshare"),
    ("amzn", "Shopping"),
    ("best buy", "Shopping"),
    ("ikea", "Shopping"),
    ("winners", "Shopping"),
    ("netflix", "Subscriptions"),
    ("spotify", "Subscriptions"),
    ("apple.com/bill", "Subscriptions"),
    ("cineplex", "Entertainment"),
    ("coursera", "Education"),
    ("air canada", "Travel"),
    ("airbnb", "Travel"),
    ("canadahelps", "Gifts & Donations"),
    *GENERIC_KEYWORDS,
)

KEYWORD_TABLES: Final = {"generic": GENERIC_KEYWORDS, "brands": BRAND_KEYWORDS}


def keyword_category(example: Example, table: Sequence[tuple[str, str]]) -> str | None:
    text = example.description.lower()
    for keyword, category in table:
        if keyword in text:
            return category
    return None
