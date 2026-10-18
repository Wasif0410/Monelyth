"""Measuring how well the pipeline categorizes: the engine behind ``scripts/eval_categorizer.py``.

The labeled transactions are categorized in memory, never touching the user's database, by
the same :class:`~monelyth_engine.categorize.pipeline.TierRunner` and tiers the app uses
(PLAN.md 3.1). Two numbers come out:

- **Before corrections:** a fresh install meeting these transactions for the first time.
- **After one round of corrections:** the user fixes (or confirms, if it needed review) the
  first transaction of each merchant, which merchant memory then remembers; the other
  transactions are measured again. This is the number PLAN.md's 90% target is about.

A transaction no tier answers counts as wrong in the accuracy: the user still has to
categorize it.
"""

from __future__ import annotations

import csv
import datetime
import sqlite3
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from monelyth_engine.categorize.memory import memory_key
from monelyth_engine.categorize.models import CategorizationInput, Categorizer, Suggestion
from monelyth_engine.categorize.pipeline import BATCH_SIZE, TierRunner
from monelyth_engine.db.memory import MemoryEntry
from monelyth_engine.db.models import Category, CategorySource
from monelyth_engine.db.schema import migrate
from monelyth_engine.normalize import normalize_merchant

LABEL_COLUMNS: Final = ("account", "date", "description", "amount_cents", "category")

TierBuilder = Callable[[Mapping[str, MemoryEntry]], Sequence[Categorizer]]
"""Builds the tiers to evaluate from the merchant memory at that point of the simulation."""


class LabelFileError(ValueError):
    """A labels file can't be read. The message names the file and row."""


@dataclass(frozen=True, slots=True)
class LabeledTransaction:
    item: CategorizationInput
    category_id: int
    """The correct category."""


@dataclass(frozen=True, slots=True)
class CategoryScore:
    name: str
    support: int
    """How many transactions truly belong to the category."""
    predicted: int
    """How many were put in it."""
    correct: int

    @property
    def precision(self) -> float | None:
        return None if self.predicted == 0 else self.correct / self.predicted

    @property
    def recall(self) -> float | None:
        return None if self.support == 0 else self.correct / self.support

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)


@dataclass(frozen=True, slots=True)
class TierScore:
    source: CategorySource
    answered: int
    correct: int


@dataclass(frozen=True, slots=True)
class Confusion:
    actual: str
    predicted: str | None
    """``None``: no tier answered."""
    count: int


@dataclass(frozen=True, slots=True)
class Evaluation:
    total: int
    correct: int
    answered: int
    needs_review: int
    """Answered with low confidence, or not answered."""
    tiers: tuple[TierScore, ...]
    """In the order the tiers are asked."""
    categories: tuple[CategoryScore, ...]
    """Every category that occurs in the labels or the predictions, by name."""
    confusions: tuple[Confusion, ...]
    """Each (actual, predicted) pair that differs, most frequent first."""

    @property
    def accuracy(self) -> float:
        return 0.0 if self.total == 0 else self.correct / self.total

    @property
    def coverage(self) -> float:
        return 0.0 if self.total == 0 else self.answered / self.total

    @property
    def answered_accuracy(self) -> float | None:
        """Accuracy of the answers given, leaving out what no tier answered."""
        return None if self.answered == 0 else self.correct / self.answered


@dataclass(frozen=True, slots=True)
class CorrectionStudy:
    before: Evaluation
    """Every transaction, with no merchant memory."""
    after: Evaluation
    """The transactions after each merchant's first, once the user corrected the firsts."""
    merchants: int
    """Distinct merchants: how many first transactions the user looked at."""
    corrections: int
    """Of those, how many the user had to fix or confirm (wrong, missing or needing review)."""


def reference_database() -> sqlite3.Connection:
    """A fresh in-memory database with the default categories and rules, to evaluate against."""
    conn = sqlite3.connect(":memory:", autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def read_labels(path: Path, categories: Sequence[Category]) -> list[LabeledTransaction]:
    """Read a labels file: ``account,date,description,amount_cents,category`` with a header,
    dates as ``YYYY-MM-DD`` and the category by name (see ``sample-data/README.md``).

    Raises:
        LabelFileError: if the file is missing columns or a row can't be read.
        OSError: if the file can't be opened.
    """
    by_name = {category.name: category.id for category in categories}
    accounts: dict[str, int] = {}
    labeled: list[LabeledTransaction] = []
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [column for column in LABEL_COLUMNS if column not in (reader.fieldnames or ())]
        if missing:
            raise LabelFileError(f"{path}: missing column(s) {', '.join(missing)}")
        for row in reader:
            where = f"{path}, line {reader.line_num}"
            try:
                category_id = by_name[row["category"]]
            except KeyError:
                raise LabelFileError(f"{where}: unknown category {row['category']!r}") from None
            try:
                posted_date = datetime.date.fromisoformat(row["date"])
                amount_cents = int(row["amount_cents"])
                merchant = normalize_merchant(row["description"])
            except ValueError as error:
                raise LabelFileError(f"{where}: {error}") from None
            account_id = accounts.setdefault(row["account"], len(accounts) + 1)
            item = CategorizationInput(
                transaction_id=len(labeled) + 1,
                account_id=account_id,
                posted_date=posted_date,
                amount_cents=amount_cents,
                description=row["description"],
                merchant=merchant,
            )
            labeled.append(LabeledTransaction(item=item, category_id=category_id))
    return labeled


def predict(
    items: Sequence[CategorizationInput],
    tiers: Sequence[Categorizer],
    categories: Sequence[Category],
) -> list[Suggestion | None]:
    """The pipeline's answers, asked in the same batches the app uses."""
    runner = TierRunner(tiers, categories)
    answers: list[Suggestion | None] = []
    for start in range(0, len(items), BATCH_SIZE):
        answers.extend(runner.suggest(items[start : start + BATCH_SIZE]))
    return answers


def score(
    labeled: Sequence[LabeledTransaction],
    predictions: Sequence[Suggestion | None],
    categories: Sequence[Category],
    *,
    tier_order: Sequence[CategorySource],
) -> Evaluation:
    names = {category.id: category.name for category in categories}
    support: Counter[int] = Counter()
    predicted: Counter[int] = Counter()
    correct_by_category: Counter[int] = Counter()
    tier_answered: Counter[CategorySource] = Counter()
    tier_correct: Counter[CategorySource] = Counter()
    confusions: Counter[tuple[str, str | None]] = Counter()
    needs_review = 0
    for truth, suggestion in zip(labeled, predictions, strict=True):
        support[truth.category_id] += 1
        if suggestion is None or suggestion.needs_review:
            needs_review += 1
        if suggestion is None:
            confusions[names[truth.category_id], None] += 1
            continue
        predicted[suggestion.category_id] += 1
        tier_answered[suggestion.source] += 1
        if suggestion.category_id == truth.category_id:
            correct_by_category[truth.category_id] += 1
            tier_correct[suggestion.source] += 1
        else:
            confusions[names[truth.category_id], names[suggestion.category_id]] += 1

    seen = set(support) | set(predicted)
    return Evaluation(
        total=len(labeled),
        correct=sum(correct_by_category.values()),
        answered=sum(predicted.values()),
        needs_review=needs_review,
        tiers=tuple(
            TierScore(source, tier_answered[source], tier_correct[source])
            for source in dict.fromkeys((*tier_order, *tier_answered))
        ),
        categories=tuple(
            sorted(
                (
                    CategoryScore(
                        names[category_id],
                        support[category_id],
                        predicted[category_id],
                        correct_by_category[category_id],
                    )
                    for category_id in seen
                ),
                key=lambda item: item.name,
            )
        ),
        confusions=tuple(
            Confusion(actual, guess, count)
            for (actual, guess), count in sorted(
                confusions.items(), key=lambda pair: (-pair[1], pair[0][0], pair[0][1] or "")
            )
        ),
    )


def study_corrections(
    labeled: Sequence[LabeledTransaction],
    build_tiers: TierBuilder,
    categories: Sequence[Category],
) -> CorrectionStudy:
    """Evaluate before and after one round of corrections (see the module docstring)."""
    items = [entry.item for entry in labeled]
    tiers = build_tiers({})
    order = [tier.source for tier in tiers]
    initial = predict(items, tiers, categories)

    in_date_order = sorted(range(len(labeled)), key=lambda i: (items[i].posted_date, i))
    firsts: set[int] = set()
    seen: set[str] = set()
    memory: dict[str, MemoryEntry] = {}
    corrected_at = datetime.datetime.now(datetime.UTC)
    for index in in_date_order:
        key = memory_key(items[index].merchant)
        if key is None or key in seen:
            continue
        seen.add(key)
        firsts.add(index)
        answer = initial[index]
        truth = labeled[index].category_id
        if answer is None or answer.needs_review or answer.category_id != truth:
            memory[key] = MemoryEntry(key, truth, CategorySource.USER, corrected_at)

    rest = [i for i in range(len(labeled)) if i not in firsts]
    later = predict([items[i] for i in rest], build_tiers(memory), categories)
    return CorrectionStudy(
        before=score(labeled, initial, categories, tier_order=order),
        after=score([labeled[i] for i in rest], later, categories, tier_order=order),
        merchants=len(firsts),
        corrections=len(memory),
    )


def format_report(title: str, study: CorrectionStudy) -> str:
    lines = [title, "=" * len(title), "", "Before any corrections", ""]
    lines += _format_evaluation(study.before)
    lines += [
        "",
        "After one round of corrections",
        "",
        f"  The user looked at the first transaction of each of {study.merchants} merchants and "
        f"fixed or confirmed {study.corrections};",
        f"  measured on the other {study.after.total} transactions.",
        "",
    ]
    lines += _format_evaluation(study.after)
    return "\n".join(lines)


def _format_evaluation(result: Evaluation) -> list[str]:
    unanswered = result.total - result.answered
    lines = [
        f"  Accuracy             {_percent(result.accuracy)}  "
        f"({result.correct} of {result.total} correct; unanswered count as wrong)",
        f"  Coverage             {_percent(result.coverage)}  "
        f"({result.answered} answered, {unanswered} left uncategorized)",
        f"  Accuracy if answered {_percent(result.answered_accuracy)}",
        f"  Needs review         {result.needs_review}",
        "",
        "  Coverage by tier     answered   share   accuracy",
    ]
    for tier in result.tiers:
        share = None if result.total == 0 else tier.answered / result.total
        accuracy = None if tier.answered == 0 else tier.correct / tier.answered
        lines.append(
            f"    {tier.source.value:<18} {tier.answered:>6}  "
            f"{_percent(share)}  {_percent(accuracy)}"
        )
    lines += ["", "  Per category         support  precision  recall      F1"]
    for category in result.categories:
        lines.append(
            f"    {category.name:<18} {category.support:>7}    {_percent(category.precision)}  "
            f"{_percent(category.recall)}  {_percent(category.f1)}"
        )
    lines += ["", "  Most common mix-ups (actual -> predicted)"]
    if not result.confusions:
        lines.append("    none")
    for confusion in result.confusions[:10]:
        guess = "(uncategorized)" if confusion.predicted is None else confusion.predicted
        lines.append(f"    {confusion.count:>4}  {confusion.actual} -> {guess}")
    return lines


def _percent(value: float | None) -> str:
    return "     -" if value is None else f"{value:6.1%}"
