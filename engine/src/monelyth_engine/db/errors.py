"""Errors raised by the storage layer. Their messages are written to be shown to the user."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from monelyth_engine.db.models import ImportRecord


class SchemaVersionError(RuntimeError):
    """The database file's schema version is not one this build of the engine can open."""


class NotFoundError(LookupError):
    """A row the caller referred to by ID does not exist."""


class DuplicateImportError(ValueError):
    """The exact same file (by SHA-256) has already been imported."""

    def __init__(self, existing: ImportRecord) -> None:
        # Stored in UTC; shown in the computer's local time so the date matches the user's day.
        imported_on = existing.imported_at.astimezone()
        super().__init__(
            f"This file was already imported on {imported_on:%Y-%m-%d} "
            f"(as {existing.file_name!r}), so nothing new was added."
        )
        self.existing = existing
