"""Made-up statements for trying Monelyth without real data.

The same generator writes the committed files in ``sample-data/`` (through
``scripts/generate_sample_data.py``) and fills the app's demo accounts (through
:func:`add_demo_data`), so both always show the same patterns.
"""

from __future__ import annotations

from monelyth_engine.demo.generator import Dataset, Month, generate
from monelyth_engine.demo.loader import DemoData, DemoDataExistsError, DemoImport, add_demo_data
from monelyth_engine.demo.statements import sample_files

SAMPLE_END_MONTH = Month(2026, 9)
"""The last month of the committed ``sample-data/`` files. Fixed so they never change unless
the generator does."""

__all__ = [
    "SAMPLE_END_MONTH",
    "Dataset",
    "DemoData",
    "DemoDataExistsError",
    "DemoImport",
    "Month",
    "add_demo_data",
    "generate",
    "sample_files",
]
