"""Measure how well categorization works on hand-labeled transactions (PLAN.md 3.1).

Usage (from the ``engine`` folder)::

    uv run python scripts/eval_categorizer.py [--labels FILE ...]

Without ``--labels`` it evaluates ``sample-data/labels.csv`` and, when it exists, the
git-ignored ``private-data/labels.csv`` with your own labeled transactions, each in its own
report. Everything runs in memory against a fresh database with the default rules; your real
database is never opened.

The tiers are the app's (``installed_extensions()`` in ``monelyth_engine.categorize.tiers``),
so a classifier or LLM tier plugged in there is measured here too. The logic lives in
:mod:`monelyth_engine.categorize.evaluation`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from monelyth_engine.categorize.evaluation import (
    LabelFileError,
    format_report,
    read_labels,
    reference_database,
    study_corrections,
)
from monelyth_engine.categorize.models import Categorizer
from monelyth_engine.categorize.tiers import core_tiers, installed_extensions
from monelyth_engine.db.categories import list_categories
from monelyth_engine.db.memory import MemoryEntry
from monelyth_engine.db.rules import list_rules

REPO_DIR: Final = Path(__file__).resolve().parents[2]
DEFAULT_LABELS: Final = (
    REPO_DIR / "sample-data" / "labels.csv",
    REPO_DIR / "private-data" / "labels.csv",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate categorization on labeled data.")
    parser.add_argument(
        "--labels",
        type=Path,
        action="append",
        metavar="FILE",
        help="a labels CSV to evaluate (repeatable); default: sample-data/labels.csv and "
        "private-data/labels.csv if present",
    )
    args = parser.parse_args(argv)
    explicit: list[Path] | None = args.labels
    paths = explicit if explicit else [path for path in DEFAULT_LABELS if path.exists()]

    conn = reference_database()
    try:
        categories = list_categories(conn)
        rules = list_rules(conn)
        extensions = installed_extensions()
        optional = (
            [] if extensions.optional_tiers is None else list(extensions.optional_tiers(conn))
        )

        def build_tiers(memory: Mapping[str, MemoryEntry]) -> list[Categorizer]:
            return [*core_tiers(memory, rules), *optional]

        reports: list[str] = []
        for path in paths:
            try:
                labeled = read_labels(path, categories)
            except (LabelFileError, OSError) as error:
                print(f"eval_categorizer: {error}", file=sys.stderr)
                return 1
            study = study_corrections(labeled, build_tiers, categories)
            title = f"{_display(path)}: {len(labeled)} labeled transactions"
            reports.append(format_report(title, study))
    finally:
        conn.close()

    print("\n\n".join(reports))
    return 0


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_DIR).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
