"""Saved CSV column mappings, so a bank's layout only has to be confirmed once."""

from __future__ import annotations

import json
import sqlite3


def get_csv_profile(conn: sqlite3.Connection, header_signature: str) -> str | None:
    """The saved mapping JSON for a CSV header, or ``None`` if this layout is new."""
    row = conn.execute(
        "SELECT mapping_json FROM csv_profiles WHERE header_signature = ?", (header_signature,)
    ).fetchone()
    return None if row is None else row["mapping_json"]


def save_csv_profile(conn: sqlite3.Connection, header_signature: str, mapping_json: str) -> None:
    """Save the mapping for a CSV header, replacing any earlier one for the same header.

    The mapping's structure belongs to the CSV importer; this only checks it is a JSON object
    so a corrupt value is caught now rather than on the next import.

    Raises:
        ValueError: if the signature is empty or the mapping is not a JSON object.
    """
    if not header_signature:
        raise ValueError("header_signature must not be empty")
    try:
        mapping: object = json.loads(mapping_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"mapping_json is not valid JSON: {error}") from error
    if not isinstance(mapping, dict):
        raise ValueError("mapping_json must be a JSON object")

    conn.execute(
        "INSERT INTO csv_profiles (header_signature, mapping_json) VALUES (?, ?) "
        "ON CONFLICT (header_signature) DO UPDATE SET mapping_json = excluded.mapping_json",
        (header_signature, mapping_json),
    )
