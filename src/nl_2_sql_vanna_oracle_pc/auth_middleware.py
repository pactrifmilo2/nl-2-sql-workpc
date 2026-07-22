"""Optional HTTP Basic Auth for exposing the app via ngrok or the public internet."""

from __future__ import annotations

import base64
import secrets

from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


class BasicAuthMiddleware:
    def __init__(self, app: ASGIApp, username: str, password: str):
        self.app = app
        self.username = username
        self.password = password

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"} or self._authorized(scope):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send(
                {
                    "type": "websocket.close",
                    "code": 1008,
                    "reason": "Authentication required",
                }
            )
            return

        response = Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="NL2SQL"'},
            content="Authentication required",
        )
        await response(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        header = Headers(scope=scope).get("Authorization", "")
        if not header.startswith("Basic "):
            return False

        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
        except (ValueError, UnicodeDecodeError):
            return False

        username_ok = secrets.compare_digest(username, self.username)
        password_ok = secrets.compare_digest(password, self.password)
        return username_ok and password_ok
