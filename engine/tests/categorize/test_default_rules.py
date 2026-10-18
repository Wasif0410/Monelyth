"""The default rules shipped in migration 002."""

from __future__ import annotations

import re
import sqlite3
from importlib import resources

import pytest

from monelyth_engine.categorize.rules import RulesCategorizer, clean_pattern
from monelyth_engine.db.models import Category
from monelyth_engine.db.rules import RuleAuthor, list_rules
from tests.categorize.conftest import item

# One "  ('pattern', 'match_type', 'Category', priority)," row per rule; a pattern may wrap.
_ROW = re.compile(r"^\s*\('((?:[^']|'')+)',\s*'(contains|regex)',\s*'([^']+)',\s*(\d+)\)", re.M)


def _rows_in_migration() -> list[tuple[str, str, str, int]]:
    sql = (
        resources.files("monelyth_engine.db")
        .joinpath("migrations", "002_default_rules.sql")
        .read_text(encoding="utf-8")
    )
    joined = re.sub(r",\s*\n\s+'(contains|regex)'", r", '\1'", sql)
    return [
        (pattern.replace("''", "'"), match_type, category, int(priority))
        for pattern, match_type, category, priority in _ROW.findall(joined)
    ]


def test_every_default_rule_is_stored_with_its_category(
    db: sqlite3.Connection, categories: dict[str, Category]
) -> None:
    expected = _rows_in_migration()
    stored = list_rules(db)

    # A misspelt category would drop its row from the INSERT ... JOIN without an error.
    assert len(stored) == len(expected) >= 100
    by_pattern = {rule.pattern: rule for rule in stored}
    for pattern, match_type, category, priority in expected:
        rule = by_pattern[pattern]
        assert rule.match_type.value == match_type
        assert rule.category_id == categories[category].id
        assert rule.priority == priority
        assert rule.created_by is RuleAuthor.SYSTEM


def test_default_patterns_are_valid_unique_and_stored_clean(db: sqlite3.Connection) -> None:
    rules = list_rules(db)

    for rule in rules:
        assert clean_pattern(rule.pattern, rule.match_type) == rule.pattern
    assert len({(rule.pattern, rule.match_type) for rule in rules}) == len(rules)


@pytest.mark.parametrize(
    ("description", "merchant", "category"),
    [
        ("UBER* EATS PENDING", "Uber Eats", "Dining Out"),
        ("UBER *TRIP HELP.UBER.COM", "Uber", "Rideshare"),
        ("AMAZON PRIME*2K3LM", "Amazon Prime", "Subscriptions"),
        ("AMZN MKTP CA*FZ1WD", "Amzn Mktp Ca Fz1wd", "Shopping"),
        ("COSTCO GAS W1234", "Costco Gas", "Gas"),
        ("COSTCO WHOLESALE #522", "Costco Wholesale", "Groceries"),
        ("ENTERPRISE RENT-A-CAR", "Enterprise Rent-A-Car", "Travel"),
        (
            "PREAUTHORIZED DEBIT HARBOURVIEW PROPERTY MGMT",
            "Harbourview Property Mgmt",
            "Rent/Mortgage",
        ),
        ("PAYROLL ACME CORP", "Payroll Acme Corp", "Salary"),
        ("NETFLIX.COM", "Netflix", "Subscriptions"),
        ("APPLE.COM/BILL", "Apple", "Subscriptions"),
        ("ONLINE PAYMENT - DEMO BANK VISA", "Online Payment Demo Bank Visa", "Transfers"),
        ("PAYMENT - THANK YOU", "Payment Thank You", "Transfers"),
        ("INTERAC E-TRANSFER FROM M. CHEN", "E-Transfer From M. Chen", "Other Income"),
        ("SQ *LITTLE PIGEON CAFE", "Little Pigeon Cafe", "Coffee"),
    ],
)
def test_default_rules_categorize_familiar_merchants(
    db: sqlite3.Connection,
    categories: dict[str, Category],
    description: str,
    merchant: str,
    category: str,
) -> None:
    [answer] = RulesCategorizer(list_rules(db)).suggest([item(description, merchant)], [])

    assert answer is not None
    assert answer.category_id == categories[category].id


@pytest.mark.parametrize(
    ("description", "merchant"),
    [
        # A local gas *utility* must not become fuel: no default rule says "gas".
        ("PREAUTHORIZED DEBIT LAKEPORT GAS", "Lakeport Gas"),
        ("QUEEN ST BARBER", "Queen St Barber"),
    ],
)
def test_default_rules_leave_ambiguous_names_alone(
    db: sqlite3.Connection, description: str, merchant: str
) -> None:
    assert RulesCategorizer(list_rules(db)).suggest([item(description, merchant)], []) == [None]
