"""Turn the engine's domain errors into HTTP responses.

Every handled error has a message written for the user, so it is returned as
``{"detail": "<message>"}`` and the UI can show it as is. Anything else is a bug and becomes a
plain 500 without internal details.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from monelyth_engine.db.errors import DuplicateImportError, NotFoundError, SchemaVersionError
from monelyth_engine.ingest.csv_statement import CsvLayoutError
from monelyth_engine.ingest.models import StatementParseError
from monelyth_engine.services.importing import FileTooLargeError, ImportRequestError

_Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]

UNEXPECTED_ERROR_MESSAGE = (
    "Something went wrong in the engine. The details are in the app's log file."
)

logger = logging.getLogger(__name__)


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


class UnhandledErrorMiddleware:
    """Answer an unexpected exception with a JSON 500 instead of a bare one.

    Starlette's own fallback runs outside every middleware, so its 500 has no CORS headers and
    the webview reports only "Failed to fetch". Installed inside the CORS middleware, this
    returns ``{"detail": ...}`` the UI can show, and logs the traceback for diagnosis.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, tracking_send)
        except Exception:
            logger.exception("Unexpected error handling %s %s", scope["method"], scope["path"])
            if response_started:
                # Too late to send a different response; let the server close the connection.
                raise
            response = JSONResponse(
                {"detail": UNEXPECTED_ERROR_MESSAGE},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            await response(scope, receive, send)
