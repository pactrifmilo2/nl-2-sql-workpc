"""Signed admin sessions shared by the admin UI and Vanna user resolver."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .settings import Settings


@dataclass(frozen=True)
class AdminSession:
    session_id: str
    username: str
    csrf_token: str
    expires_at: int


class AdminSessionStore(Protocol):
    def create_admin_session(
        self, *, session_id: str, username: str, expires_at: int
    ) -> None: ...

    def is_admin_session_active(
        self, *, session_id: str, username: str, expires_at: int
    ) -> bool: ...

    def revoke_admin_session(self, session_id: str) -> None: ...


class AdminAuth:
    def __init__(
        self,
        settings: Settings,
        session_store: AdminSessionStore | None = None,
    ):
        self.settings = settings
        self.session_store = session_store

    @property
    def enabled(self) -> bool:
        return self.settings.admin_auth_enabled

    @property
    def cookie_name(self) -> str:
        return self.settings.admin_session_cookie_name

    def authenticate(self, username: str, password: str) -> bool:
        if not self.enabled:
            return False
        username_ok = secrets.compare_digest(username, self.settings.admin_auth_user)
        password_ok = secrets.compare_digest(password, self.settings.admin_auth_password)
        return username_ok and password_ok

    def issue_token(self, username: str) -> tuple[str, AdminSession]:
        if not self.enabled:
            raise RuntimeError("Admin authentication is not configured")
        expires_at = int(time.time()) + self.settings.admin_session_ttl_hours * 3600
        session = AdminSession(
            session_id=secrets.token_urlsafe(24),
            username=username,
            csrf_token=secrets.token_urlsafe(24),
            expires_at=expires_at,
        )
        payload = {
            "session_id": session.session_id,
            "username": session.username,
            "csrf": session.csrf_token,
            "expires_at": session.expires_at,
        }
        encoded = self._encode(json.dumps(payload, separators=(",", ":")).encode())
        signature = self._sign(encoded)
        if self.session_store is not None:
            self.session_store.create_admin_session(
                session_id=session.session_id,
                username=session.username,
                expires_at=session.expires_at,
            )
        return f"{encoded}.{signature}", session

    def verify_token(self, token: str | None) -> AdminSession | None:
        if not self.enabled or not token:
            return None
        encoded, separator, signature = token.partition(".")
        if not separator or not hmac.compare_digest(signature, self._sign(encoded)):
            return None
        try:
            payload: dict[str, Any] = json.loads(self._decode(encoded))
            session_id = str(payload["session_id"])
            username = str(payload["username"])
            csrf_token = str(payload["csrf"])
            expires_at = int(payload["expires_at"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if expires_at <= int(time.time()):
            return None
        if not secrets.compare_digest(username, self.settings.admin_auth_user):
            return None
        if self.session_store is not None and not self.session_store.is_admin_session_active(
            session_id=session_id,
            username=username,
            expires_at=expires_at,
        ):
            return None
        return AdminSession(
            session_id=session_id,
            username=username,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    def verify_csrf(self, session: AdminSession, supplied_token: str) -> bool:
        return bool(supplied_token) and secrets.compare_digest(
            session.csrf_token, supplied_token
        )

    def revoke_session(self, session: AdminSession) -> None:
        if self.session_store is not None:
            self.session_store.revoke_admin_session(session.session_id)

    def _sign(self, encoded_payload: str) -> str:
        digest = hmac.new(
            self.settings.admin_session_secret.encode(),
            encoded_payload.encode(),
            hashlib.sha256,
        ).digest()
        return self._encode(digest)

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _decode(value: str) -> str:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding).decode()


def create_admin_auth(
    settings: Settings,
    session_store: AdminSessionStore | None = None,
) -> AdminAuth:
    return AdminAuth(settings, session_store)
