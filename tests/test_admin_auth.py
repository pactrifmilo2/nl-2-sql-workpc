import asyncio
import base64

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from vanna.core.user import RequestContext

from nl_2_sql_vanna_oracle_pc.admin_auth import AdminAuth
from nl_2_sql_vanna_oracle_pc.auth import SimpleUserResolver
from nl_2_sql_vanna_oracle_pc.auth_middleware import BasicAuthMiddleware
from nl_2_sql_vanna_oracle_pc.settings import Settings


def admin_settings(**overrides) -> Settings:
    values = {
        "admin_auth_user": "reviewer",
        "admin_auth_password": "strong-password",
        "admin_session_secret": "test-secret-that-is-long-and-random",
        "admin_session_cookie_secure": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_admin_session_is_signed_and_tamper_resistant() -> None:
    auth = AdminAuth(admin_settings())

    assert auth.authenticate("reviewer", "strong-password")
    assert not auth.authenticate("reviewer", "wrong")

    token, issued = auth.issue_token("reviewer")
    verified = auth.verify_token(token)

    assert verified == issued
    assert auth.verify_csrf(verified, issued.csrf_token)
    assert auth.verify_token(token + "tampered") is None


def test_only_signed_admin_session_grants_admin_group() -> None:
    auth = AdminAuth(admin_settings())
    resolver = SimpleUserResolver(auth)
    spoofed_context = RequestContext(
        cookies={"vanna_email": "admin@example.com"}
    )

    spoofed = asyncio.run(resolver.resolve_user(spoofed_context))

    assert spoofed.group_memberships == ["user"]

    token, _ = auth.issue_token("reviewer")
    signed_context = RequestContext(cookies={auth.cookie_name: token})
    admin = asyncio.run(resolver.resolve_user(signed_context))

    assert admin.id == "reviewer"
    assert admin.group_memberships == ["admin"]


def test_app_basic_auth_also_protects_websocket_chat() -> None:
    app = FastAPI()

    @app.websocket("/chat")
    async def chat(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("ok")

    app.add_middleware(
        BasicAuthMiddleware,
        username="app-user",
        password="app-password",
    )
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/chat"):
            pass
    assert denied.value.code == 1008

    encoded = base64.b64encode(b"app-user:app-password").decode()
    with client.websocket_connect(
        "/chat", headers={"Authorization": f"Basic {encoded}"}
    ) as websocket:
        assert websocket.receive_text() == "ok"
