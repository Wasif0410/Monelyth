"""Request authentication for the local API."""

from __future__ import annotations

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# WebSocket close code for "policy violation", sent when a socket has no valid token.
_WS_POLICY_VIOLATION = 1008


class BearerTokenMiddleware:
    """Reject every HTTP or WebSocket request that lacks ``Authorization: Bearer <token>``.

    The engine binds to loopback, but any program on the machine, and any web page open in
    a browser, can still send requests to ``127.0.0.1``. The token is generated fresh by the
    desktop shell on every launch and only handed to the app's own webview, so nothing else
    can read the user's data.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._token = token.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or self._is_authorized(scope):
            await self._app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": _WS_POLICY_VIOLATION})
            return

        response = JSONResponse(
            {"detail": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)

    def _is_authorized(self, scope: Scope) -> bool:
        headers: list[tuple[bytes, bytes]] = scope["headers"]
        values = [value for name, value in headers if name == b"authorization"]
        if len(values) != 1:
            return False

        scheme, _, credentials = values[0].partition(b" ")
        if scheme.lower() != b"bearer":
            return False
        # Constant-time comparison so response timing reveals nothing about the token.
        return hmac.compare_digest(credentials, self._token)
