"""POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me, and the CSRF guard on every
POST. Against the per-test SQLite file; the ASGI client's peer is 127.0.0.1 (a trusted proxy),
so a test picks its client IP with X-Forwarded-For."""

import asyncio
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from argon2 import PasswordHasher

from app.auth import passwords, sessions, users
from app.auth.deps import SESSION_COOKIE
from app.config import get_settings
from app.db import UserRow, session_scope, utcnow
from app.main import app
from app.schemas import LOGIN_FAILED, LOGIN_THROTTLED, Me
from tests.sse import client

PASSWORD = "correct horse battery"
CSRF = {"X-Requested-With": "fetch"}


def https_client(ip: str = "198.51.100.10") -> httpx.AsyncClient:
    """Over https, like prod, so the Secure cookie is kept and sent back."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
        headers={**CSRF, "X-Forwarded-For": ip},
    )


def make_user(email: str = "ana@example.com", password: str | None = PASSWORD) -> UserRow:
    hashed = passwords.hash_password(password) if password is not None else None
    return users.create_user(email, password_hash=hashed)


def disable(user_id: str) -> None:
    with session_scope() as s:  # what `make disable-user` (#7) will do
        row = s.get(UserRow, user_id)
        assert row is not None
        row.disabled_at = utcnow()


async def login(c: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await c.post("/api/auth/login", json={"email": email, "password": password})


def set_cookie_header(response: httpx.Response) -> str:
    [header] = [v for k, v in response.headers.multi_items() if k == "set-cookie"]
    return header


async def test_sign_in_me_and_sign_out() -> None:
    user = make_user()
    async with https_client() as c:
        signed_in = await login(c, "ana@example.com", PASSWORD)
        assert signed_in.status_code == 200
        assert Me.model_validate(signed_in.json()).email == "ana@example.com"
        token = c.cookies[SESSION_COOKIE]
        assert sessions.resolve(token) is not None

        me = await c.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["id"] == user.id
        assert me.json()["has_password"] is True

        out = await c.post("/api/auth/logout")
        assert out.status_code == 204
        assert 'tmrx_session=""' in set_cookie_header(out)
        assert sessions.resolve(token) is None  # the row is gone, not just the cookie
        assert (await c.get("/api/auth/me")).status_code == 401


async def test_the_cookie_is_httponly_lax_secure_and_lasts_30_days() -> None:
    make_user()
    async with https_client() as c:
        header = set_cookie_header(await login(c, "ana@example.com", PASSWORD)).lower()
    assert header.startswith(f"{SESSION_COOKIE}=")
    for flag in ("httponly", "samesite=lax", "secure", "max-age=2592000", "path=/"):
        assert flag in header


@pytest.fixture
def insecure_cookie() -> Iterator[None]:
    settings = get_settings()
    original, settings.session_cookie_secure = settings.session_cookie_secure, False
    yield
    settings.session_cookie_secure = original


async def test_secure_comes_from_settings_for_http_localhost(insecure_cookie: None) -> None:
    make_user()
    async with https_client() as c:
        header = set_cookie_header(await login(c, "ana@example.com", PASSWORD)).lower()
    assert "secure" not in header
    assert "httponly" in header


async def test_email_is_matched_ignoring_case_and_spaces() -> None:
    make_user()
    async with https_client() as c:
        assert (await login(c, "  Ana@Example.COM ", PASSWORD)).status_code == 200


async def test_every_failure_gives_the_same_answer() -> None:
    make_user()
    disable(make_user("off@example.com").id)
    make_user("passkey@example.com", password=None)
    answers: list[tuple[int, Any]] = []
    for email, password in [
        ("nobody@example.com", PASSWORD),  # unknown email
        ("ana@example.com", "wrong horse battery"),  # wrong password
        ("off@example.com", PASSWORD),  # disabled, right password
        ("passkey@example.com", PASSWORD),  # no password set
    ]:
        async with https_client(ip=f"198.51.100.{len(answers) + 20}") as c:
            r = await login(c, email, password)
            assert SESSION_COOKIE not in c.cookies
        answers.append((r.status_code, r.json()))
    assert answers == [(401, {"detail": LOGIN_FAILED})] * 4


async def test_an_unknown_email_still_does_the_hash_work(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_verify = PasswordHasher.verify

    def spy(self: PasswordHasher, hash: str, password: str) -> bool:
        calls.append(password)
        return real_verify(self, hash, password)

    monkeypatch.setattr(PasswordHasher, "verify", spy)
    make_user("passkey@example.com", password=None)
    async with https_client() as c:
        await login(c, "nobody@example.com", PASSWORD)
        await login(c, "passkey@example.com", PASSWORD)
    assert calls == [PASSWORD, PASSWORD]


async def test_five_failures_for_one_email_throttle_even_the_right_password() -> None:
    make_user()
    for i in range(5):
        async with https_client(ip=f"203.0.113.{i}") as c:
            assert (await login(c, "ana@example.com", "wrong horse battery")).status_code == 401
    async with https_client(ip="203.0.113.99") as c:
        r = await login(c, "ana@example.com", PASSWORD)
        assert (r.status_code, r.json()) == (429, {"detail": LOGIN_THROTTLED})
        assert SESSION_COOKIE not in c.cookies
    # Another account is untouched: accounts don't lock each other out.
    make_user("bo@example.com")
    async with https_client(ip="203.0.113.98") as c:
        assert (await login(c, "bo@example.com", PASSWORD)).status_code == 200


async def test_five_failures_from_one_ip_throttle_that_ip() -> None:
    make_user()
    async with https_client(ip="203.0.113.50") as c:
        for i in range(5):
            assert (await login(c, f"guess{i}@example.com", PASSWORD)).status_code == 401
        r = await login(c, "ana@example.com", PASSWORD)
        assert (r.status_code, r.json()) == (429, {"detail": LOGIN_THROTTLED})
    async with https_client(ip="203.0.113.51") as c:
        assert (await login(c, "ana@example.com", PASSWORD)).status_code == 200


async def test_a_burst_of_parallel_guesses_still_gets_only_five() -> None:
    make_user()
    async with https_client(ip="203.0.113.60") as c:
        answers = await asyncio.gather(
            *(login(c, "ana@example.com", f"wrong horse battery {i}") for i in range(12))
        )
    codes = sorted(r.status_code for r in answers)
    assert codes == [401] * 5 + [429] * 7


async def test_sign_in_upgrades_an_outdated_hash() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    users.create_user("ana@example.com", password_hash=weak)
    async with https_client() as c:
        assert (await login(c, "ana@example.com", PASSWORD)).status_code == 200
    user = users.find_by_email("ana@example.com")
    assert user is not None and user.password_hash is not None
    assert user.password_hash != weak
    assert passwords.verify_password(user.password_hash, PASSWORD) == (True, None)
    assert user.last_login_at is not None


async def test_me_without_a_session_is_401() -> None:
    async with https_client() as c:
        assert (await c.get("/api/auth/me")).status_code == 401
        c.cookies.set(SESSION_COOKIE, "made-up")
        assert (await c.get("/api/auth/me")).status_code == 401


async def test_signing_out_without_a_session_is_fine() -> None:
    async with https_client() as c:
        assert (await c.post("/api/auth/logout")).status_code == 204


async def test_a_post_without_x_requested_with_is_refused_on_any_route() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as bare:
        r = await bare.post("/api/feasibility/NCT00000000", json={})
        assert r.status_code == 403
        r = await bare.post("/api/auth/login", json={"email": "a@b.c", "password": PASSWORD})
        assert r.status_code == 403
        assert (await bare.get("/api/health")).status_code == 200  # reads are unaffected
    async with client() as c:  # the shared test client sends the header
        r = await c.post("/api/feasibility/NCT00000000", json={})
        assert r.status_code != 403
