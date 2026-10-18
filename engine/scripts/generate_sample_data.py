"""Generate the fake demo statements in ``sample-data/``.

Usage (from the ``engine`` folder)::

    uv run python scripts/generate_sample_data.py [--end-month YYYY-MM] [--output-dir DIR]

Writes twelve months of made-up activity for one checking account and one credit card, ending
with ``--end-month`` (default 2026-09). The generator and the file formats live in
:mod:`monelyth_engine.demo`, which the app also uses for its "Try demo data" option; this script
only writes the files. The output depends only on the arguments, so the committed files can be
reproduced byte for byte.
"""

from __future__ import annotations

import argparse
import datetime
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from monelyth_engine.demo import SAMPLE_END_MONTH, Month, generate, sample_files

ENGINE_DIR: Final = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR: Final = ENGINE_DIR.parent / "sample-data"
DEFAULT_END_MONTH: Final = f"{SAMPLE_END_MONTH.year:04d}-{SAMPLE_END_MONTH.month:02d}"


def write_all(files: dict[str, str], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in files.items():
        path = output_dir / name
        # newline="" keeps "\n" on every platform, so the bytes match .gitattributes (LF).
        with path.open("w", encoding="utf-8", newline="") as file:
            file.write(text)
        written.append(path)
    return written


def _parse_month(text: str) -> Month:
    try:
        parsed = datetime.datetime.strptime(text, "%Y-%m")
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {text!r}") from None
    return Month(parsed.year, parsed.month)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the fake demo statements and their category labels."
    )
    parser.add_argument(
        "--end-month",
        type=_parse_month,
        default=SAMPLE_END_MONTH,
        metavar="YYYY-MM",
        help=f"last of the twelve months to generate (default {DEFAULT_END_MONTH})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="folder to write into (default: sample-data/ at the repository root)",
    )
    args = parser.parse_args(argv)
    end_month: Month = args.end_month
    output_dir: Path = args.output_dir

    dataset = generate(end_month)
    for path in write_all(sample_files(dataset), output_dir):
        print(f"Wrote {path}")
    print(
        f"{len(dataset.checking)} checking and {len(dataset.card)} credit card transactions "
        f"from {dataset.start} to {dataset.end}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
