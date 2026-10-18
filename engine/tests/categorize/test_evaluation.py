from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pytest

from monelyth_engine.categorize.evaluation import (
    CategoryScore,
    Confusion,
    LabeledTransaction,
    LabelFileError,
    TierScore,
    format_report,
    read_labels,
    reference_database,
    score,
    study_corrections,
)
from monelyth_engine.categorize.memory import user_memory
from monelyth_engine.categorize.models import Categorizer, Suggestion
from monelyth_engine.categorize.rules import RulesCategorizer
from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.memory import MemoryEntry
from monelyth_engine.db.models import Category, CategorySource
from tests.categorize.conftest import item, rule

ENGINE_DIR: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = ENGINE_DIR / "scripts" / "eval_categorizer.py"
SAMPLE_LABELS: Final = ENGINE_DIR.parent / "sample-data" / "labels.csv"


@pytest.fixture
def reference() -> list[Category]:
    conn = reference_database()
    try:
        return list_categories(conn)
    finally:
        conn.close()


def _id(categories: Sequence[Category], name: str) -> int:
    return next(category.id for category in categories if category.name == name)


def test_score_counts_accuracy_coverage_tiers_and_mix_ups(reference: list[Category]) -> None:
    coffee, dining = _id(reference, "Coffee"), _id(reference, "Dining Out")
    labeled = [
        LabeledTransaction(item("A", transaction_id=1), coffee),
        LabeledTransaction(item("B", transaction_id=2), coffee),
        LabeledTransaction(item("C", transaction_id=3), dining),
        LabeledTransaction(item("D", transaction_id=4), dining),
    ]
    predictions = [
        Suggestion(coffee, CategorySource.RULE, 1.0),
        Suggestion(dining, CategorySource.RULE, 1.0),
        Suggestion(dining, CategorySource.LLM, 0.5),
        None,
    ]

    result = score(
        labeled,
        predictions,
        reference,
        tier_order=[CategorySource.MEMORY, CategorySource.RULE, CategorySource.LLM],
    )

    assert (result.total, result.correct, result.answered, result.needs_review) == (4, 2, 3, 2)
    assert result.accuracy == 0.5
    assert result.coverage == 0.75
    assert result.answered_accuracy == pytest.approx(2 / 3)
    assert result.tiers == (
        TierScore(CategorySource.MEMORY, 0, 0),
        TierScore(CategorySource.RULE, 2, 1),
        TierScore(CategorySource.LLM, 1, 1),
    )
    assert result.categories == (
        CategoryScore("Coffee", support=2, predicted=1, correct=1),
        CategoryScore("Dining Out", support=2, predicted=2, correct=1),
    )
    assert result.confusions == (
        Confusion("Coffee", "Dining Out", 1),
        Confusion("Dining Out", None, 1),
    )


def test_category_score_handles_empty_cases() -> None:
    assert CategoryScore("X", support=0, predicted=0, correct=0).f1 is None
    assert CategoryScore("X", support=2, predicted=0, correct=0).precision is None
    assert CategoryScore("X", support=4, predicted=2, correct=1).f1 == pytest.approx(1 / 3)


def test_one_round_of_corrections_teaches_memory_the_first_of_each_merchant(
    reference: list[Category],
) -> None:
    coffee, groceries = _id(reference, "Coffee"), _id(reference, "Groceries")
    rules = [rule("starbucks", coffee)]
    labeled = [
        LabeledTransaction(item("STARBUCKS 1", "Starbucks", transaction_id=1), coffee),
        LabeledTransaction(item("LOCAL MARKET", "Local Market", transaction_id=2), groceries),
        LabeledTransaction(item("LOCAL MARKET", "Local Market", transaction_id=3), groceries),
        LabeledTransaction(item("STARBUCKS 2", "Starbucks", transaction_id=4), coffee),
        LabeledTransaction(item("LOCAL MARKET", "Local Market", transaction_id=5), groceries),
    ]
    memories: list[dict[str, MemoryEntry]] = []

    def build(memory: Mapping[str, MemoryEntry]) -> list[Categorizer]:
        memories.append(dict(memory))
        return [user_memory(memory), RulesCategorizer(rules)]

    study = study_corrections(labeled, build, reference)

    assert (study.before.total, study.before.correct) == (5, 2)
    # The user saw both merchants' first transactions and fixed the uncategorized one.
    assert (study.merchants, study.corrections) == (2, 1)
    assert list(memories[1]) == ["local market"]
    assert (study.after.total, study.after.correct) == (3, 3)
    assert study.after.tiers == (
        TierScore(CategorySource.MEMORY, 2, 2),
        TierScore(CategorySource.RULE, 1, 1),
    )

    report = format_report("labels.csv: 5 labeled transactions", study)
    assert "Before any corrections" in report
    assert "fixed or confirmed 1" in report
    assert "Local Market" not in report  # Only category names, never merchants.
    assert "Groceries -> (uncategorized)" in report


def test_read_labels(tmp_path: Path, reference: list[Category]) -> None:
    path = tmp_path / "labels.csv"
    path.write_text(
        "﻿account,date,description,amount_cents,category\n"
        "checking,2026-09-01,SQ *BLUE BOTTLE 0423,-525,Coffee\n"
        "card,2026-09-02,PAYROLL ACME CORP,250000,Salary\n"
        "checking,2026-09-03,LOBLAWS,-8210,Groceries\n",
        encoding="utf-8",
    )

    labeled = read_labels(path, reference)

    assert [entry.item.merchant for entry in labeled] == [
        "Blue Bottle",
        "Payroll Acme Corp",
        "Loblaws",
    ]
    assert [entry.item.account_id for entry in labeled] == [1, 2, 1]
    assert [entry.item.transaction_id for entry in labeled] == [1, 2, 3]
    assert labeled[1].category_id == _id(reference, "Salary")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("account,date,description\n", "missing column"),
        (
            "account,date,description,amount_cents,category\nc,2026-09-01,X,-1,Pets\n",
            "line 2: unknown category 'Pets'",
        ),
        (
            "account,date,description,amount_cents,category\nc,09/01/2026,X,-1,Other\n",
            "line 2:",
        ),
        ("account,date,description,amount_cents,category\nc,2026-09-01,X,1.5,Other\n", "line 2:"),
    ],
)
def test_read_labels_names_the_problem(
    tmp_path: Path, reference: list[Category], text: str, message: str
) -> None:
    path = tmp_path / "labels.csv"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(LabelFileError, match=message):
        read_labels(path, reference)


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=ENGINE_DIR,
    )


def test_script_reports_on_the_sample_labels() -> None:
    result = _run_script("--labels", str(SAMPLE_LABELS))

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("sample-data/labels.csv: ")
    for heading in ("Accuracy", "Coverage by tier", "Per category", "After one round"):
        assert heading in result.stdout


def test_script_fails_cleanly_on_a_bad_file(tmp_path: Path) -> None:
    result = _run_script("--labels", str(tmp_path / "missing.csv"))

    assert result.returncode == 1
    assert "eval_categorizer:" in result.stderr
    assert result.stdout == ""
