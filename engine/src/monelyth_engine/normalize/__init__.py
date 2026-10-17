"""Clean bank transaction descriptions into merchant names. Knows nothing about the database."""

from __future__ import annotations

from monelyth_engine.normalize.merchant import merchant_key, normalize_merchant

__all__ = ["merchant_key", "normalize_merchant"]
