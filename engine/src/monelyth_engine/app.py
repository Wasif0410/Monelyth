"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from monelyth_engine import __version__
from monelyth_engine.api import health
from monelyth_engine.config import HOST, Settings
from monelyth_engine.security import BearerTokenMiddleware


def create_app(settings: Settings) -> FastAPI:
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
    app.include_router(health.router)

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
