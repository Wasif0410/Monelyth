"""Turn the engine's domain errors into HTTP responses.

Every handled error has a message written for the user, so it is returned as
``{"detail": "<message>"}`` and the UI can show it as is. Anything else is a bug and becomes a
plain 500 without internal details.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from monelyth_engine.db.errors import DuplicateImportError, NotFoundError, SchemaVersionError
from monelyth_engine.ingest.csv_statement import CsvLayoutError
from monelyth_engine.ingest.models import StatementParseError
from monelyth_engine.services.importing import FileTooLargeError, ImportRequestError

_Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def install_error_handlers(app: FastAPI) -> None:
    # Starlette picks the handler for the most specific class in an error's MRO, so
    # FileTooLargeError gets 413 even though it is also an ImportRequestError.
    statuses: dict[type[Exception], int] = {
        FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
        ImportRequestError: status.HTTP_422_UNPROCESSABLE_CONTENT,
        StatementParseError: status.HTTP_422_UNPROCESSABLE_CONTENT,
        CsvLayoutError: status.HTTP_422_UNPROCESSABLE_CONTENT,
        NotFoundError: status.HTTP_404_NOT_FOUND,
        SchemaVersionError: status.HTTP_503_SERVICE_UNAVAILABLE,
    }
    for error_type, status_code in statuses.items():
        app.add_exception_handler(error_type, _message_handler(status_code))
    app.add_exception_handler(DuplicateImportError, _duplicate_import)


def _message_handler(status_code: int) -> _Handler:
    async def handle(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=status_code)

    return handle


async def _duplicate_import(_request: Request, error: Exception) -> JSONResponse:
    # Registered for DuplicateImportError only; the check narrows the type for the checker.
    import_id = error.existing.id if isinstance(error, DuplicateImportError) else None
    return JSONResponse(
        {"detail": str(error), "import_id": import_id},
        status_code=status.HTTP_409_CONFLICT,
    )
