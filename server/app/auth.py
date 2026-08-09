"""Optional, cookie-based authentication for the Jianghu Online API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request


SESSION_COOKIE = "jianghu_session"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool = False
    users: dict[str, str] | None = None
    secret: str = ""
    session_ttl_minutes: int = 480
    max_attempts: int = 5
    login_window_seconds: int = 900
    lockout_seconds: int = 900
    trust_proxy: bool = False
    cookie_secure: bool = False

    @classmethod
    def from_environment(cls) -> "AuthSettings":
        enabled = _as_bool(os.getenv("AUTH_ENABLED"))
        users: dict[str, str] = {}
        raw_users = os.getenv("AUTH_USERS", "")
        for item in raw_users.split(","):
            if not item.strip() or ":" not in item:
                continue
            username, password = item.split(":", 1)
            if username.strip() and password:
                users[username.strip()] = password
        username = os.getenv("AUTH_USERNAME", "").strip()
        password = os.getenv("AUTH_PASSWORD", "")
        if username and password:
            users.setdefault(username, password)
        return cls(
            enabled=enabled,
            users=users,
            secret=os.getenv("AUTH_SESSION_SECRET", ""),
            session_ttl_minutes=_as_positive_int(os.getenv("AUTH_SESSION_TTL_MINUTES"), 480),
            max_attempts=_as_positive_int(os.getenv("AUTH_LOGIN_MAX_ATTEMPTS"), 5),
            login_window_seconds=_as_positive_int(os.getenv("AUTH_LOGIN_WINDOW_SECONDS"), 900),
            lockout_seconds=_as_positive_int(os.getenv("AUTH_LOCKOUT_SECONDS"), 900),
            trust_proxy=_as_bool(os.getenv("AUTH_TRUST_PROXY")),
            cookie_secure=_as_bool(os.getenv("AUTH_COOKIE_SECURE")),
        )


class AuthManager:
    def __init__(self, settings: AuthSettings | None = None) -> None:
        self.settings = settings or AuthSettings.from_environment()
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._locked_until: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()
        if self.settings.enabled and (not self.settings.users or not self.settings.secret):
            raise RuntimeError("AUTH_ENABLED requires AUTH_USERS (or AUTH_USERNAME/AUTH_PASSWORD) and AUTH_SESSION_SECRET")

    def client_ip(self, request: Request) -> str:
        if self.settings.trust_proxy:
            forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if forwarded:
                return forwarded
        return request.client.host if request.client else "unknown"

    def _key(self, client_ip: str, username: str) -> tuple[str, str]:
        return client_ip, username.casefold().strip()

    def remaining_lock_seconds(self, client_ip: str, username: str) -> int:
        now = time.monotonic()
        with self._lock:
            locked_until = self._locked_until.get(self._key(client_ip, username), 0)
            if locked_until <= now:
                self._locked_until.pop(self._key(client_ip, username), None)
                return 0
            return max(1, int(locked_until - now + 0.999))

    def record_failure(self, client_ip: str, username: str) -> int:
        now = time.monotonic()
        key = self._key(client_ip, username)
        with self._lock:
            recent = [at for at in self._failures.get(key, []) if now - at < self.settings.login_window_seconds]
            recent.append(now)
            self._failures[key] = recent
            if len(recent) >= self.settings.max_attempts:
                self._locked_until[key] = now + self.settings.lockout_seconds
                self._failures.pop(key, None)
                return self.settings.lockout_seconds
        return 0

    def clear_failures(self, client_ip: str, username: str) -> None:
        key = self._key(client_ip, username)
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def verify_credentials(self, username: str, password: str) -> bool:
        if not self.settings.enabled:
            return True
        expected = (self.settings.users or {}).get(username)
        # Compare a dummy value too, keeping unknown-user timing close to a bad password.
        candidate = expected if expected is not None else "\0"
        return expected is not None and hmac.compare_digest(candidate, password)

    def issue_session(self, username: str) -> str:
        expires = int(time.time()) + self.settings.session_ttl_minutes * 60
        payload = f"{username}\n{expires}\n{secrets.token_urlsafe(18)}".encode()
        payload_encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(self.settings.secret.encode(), payload_encoded.encode(), hashlib.sha256).hexdigest()
        return f"{payload_encoded}.{signature}"

    def session_username(self, token: str | None) -> str | None:
        if not self.settings.enabled:
            return None
        if not token or "." not in token:
            return None
        payload_encoded, signature = token.rsplit(".", 1)
        expected_signature = hmac.new(self.settings.secret.encode(), payload_encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_signature, signature):
            return None
        try:
            payload = base64.urlsafe_b64decode(payload_encoded + "=" * (-len(payload_encoded) % 4)).decode()
            username, expires, _nonce = payload.split("\n", 2)
        except (ValueError, UnicodeDecodeError):
            return None
        if int(expires) < int(time.time()) or username not in (self.settings.users or {}):
            return None
        return username

    def authenticated_username(self, request: Request) -> str | None:
        return self.session_username(request.cookies.get(SESSION_COOKIE))

    def require_authenticated(self, request: Request) -> str | None:
        if not self.settings.enabled:
            return None
        username = self.authenticated_username(request)
        if not username:
            raise HTTPException(status_code=401, detail="login_required")
        return username
