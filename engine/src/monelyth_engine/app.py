"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from monelyth_engine import __version__
from monelyth_engine.api import (
    accounts,
    categories,
    data,
    demo,
    health,
    imports,
    transactions,
)
from monelyth_engine.api.errors import install_error_handlers
from monelyth_engine.config import HOST, Settings
from monelyth_engine.database import Database
from monelyth_engine.security import BearerTokenMiddleware


def create_app(settings: Settings) -> FastAPI:
    """Build the app and open (creating or migrating) the user's database.

    Raises:
        SchemaVersionError: if the database was created by a newer version of Monelyth.
        sqlite3.Error: if the database file cannot be opened.
        OSError: if the data folder cannot be created.
    """
    database = Database(settings.data_dir)
    database.initialize()

    app = FastAPI(
        title="Monelyth Engine",
        version=__version__,
        # Interactive docs are not served: the app has no browser user to read them, and the
        # OpenAPI schema is still available in-process (``app.openapi()``) to generate
        # TypeScript types for the UI.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.database = database
    install_error_handlers(app)
    for module in (health, accounts, categories, imports, transactions, data, demo):
        app.include_router(module.router)

    # Starlette runs the middleware added last first, so requests pass through, in order:
    # CORS -> trusted host -> token check -> routes. CORS must be outermost so browser
    # preflight requests (which never carry the token) are answered, and so even a 401
    # carries CORS headers the UI can read.
    app.add_middleware(BearerTokenMiddleware, token=settings.token)
    # Rejects requests whose Host header is not loopback, which blocks DNS-rebinding attacks.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[HOST, "localhost"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
        max_age=600,
    )
    return app
