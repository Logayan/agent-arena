import httpx
import pytest

from server.app.auth import AuthManager, AuthSettings, SESSION_COOKIE
from server.app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def enabled_auth(*, max_attempts: int = 3) -> AuthManager:
    return AuthManager(AuthSettings(
        enabled=True,
        users={"admin": "correct horse battery staple"},
        secret="a-test-only-session-secret-with-enough-length",
        max_attempts=max_attempts,
        login_window_seconds=900,
        lockout_seconds=120,
    ))


@pytest.mark.anyio
async def test_login_disabled_keeps_existing_api_access(monkeypatch) -> None:
    monkeypatch.setattr("server.app.main.auth_manager", AuthManager(AuthSettings(enabled=False)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        session = await client.get("/api/auth/session")
        overview = await client.get("/api/platform/overview")
    assert session.json() == {"enabled": False, "authenticated": True, "username": None}
    assert overview.status_code == 200


@pytest.mark.anyio
async def test_protected_api_requires_valid_cookie_and_logout_revokes_access(monkeypatch) -> None:
    monkeypatch.setattr("server.app.main.auth_manager", enabled_auth())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/health")).status_code == 200
        assert (await client.get("/api/platform/overview")).status_code == 401
        logged_in = await client.post("/api/auth/login", json={"username": "admin", "password": "correct horse battery staple"})
        assert logged_in.status_code == 200
        assert SESSION_COOKIE in client.cookies
        assert (await client.get("/api/platform/overview")).status_code == 200
        assert (await client.post("/api/auth/logout")).status_code == 200
        assert (await client.get("/api/platform/overview")).status_code == 401


@pytest.mark.anyio
async def test_bad_password_and_unknown_account_have_the_same_response(monkeypatch) -> None:
    monkeypatch.setattr("server.app.main.auth_manager", enabled_auth())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        wrong_password = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        unknown_user = await client.post("/api/auth/login", json={"username": "nobody", "password": "wrong"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json() == {"detail": "用户名或密码错误"}


@pytest.mark.anyio
async def test_login_failures_lock_the_same_ip_and_account(monkeypatch) -> None:
    monkeypatch.setattr("server.app.main.auth_manager", enabled_auth(max_attempts=3))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            response = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
            assert response.status_code == 401
        locked = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        still_locked = await client.post("/api/auth/login", json={"username": "admin", "password": "correct horse battery staple"})
    assert locked.status_code == still_locked.status_code == 429
    assert locked.headers["retry-after"]
    assert locked.json() == still_locked.json() == {"detail": "登录尝试过多，请稍后再试。"}


@pytest.mark.anyio
async def test_successful_login_clears_its_previous_failed_attempts(monkeypatch) -> None:
    monkeypatch.setattr("server.app.main.auth_manager", enabled_auth(max_attempts=3))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})).status_code == 401
        assert (await client.post("/api/auth/login", json={"username": "admin", "password": "correct horse battery staple"})).status_code == 200
        assert (await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})).status_code == 401
        assert (await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})).status_code == 401
        locked = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert locked.status_code == 429
