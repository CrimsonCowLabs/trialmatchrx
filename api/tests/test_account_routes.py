"""The account page's API (SPEC.md "Marketing and accounts", `/app/account`): set or change
your password (POST /api/auth/password), remove a passkey (DELETE /api/auth/passkeys/{id}),
and sign out everywhere (POST /api/auth/logout-everywhere)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from app.auth import passkeys, passwords, sessions
from app.auth.deps import SESSION_COOKIE
from app.db import UserRow
from app.schemas import LOGIN_THROTTLED, PASSWORD_WRONG
from tests.test_auth_passkeys import passkey_login
from tests.test_auth_routes import PASSWORD, https_client, login, make_user
from tests.webauthn_fake import FakeAuthenticator

NEW_PASSWORD = "a brand new passphrase"


def add_device(user: UserRow, n: int = 1) -> FakeAuthenticator:
    """Give `user` a passkey on a new fake device, without a session."""
    device = FakeAuthenticator(credential_id=f"fake-credential-{n}".encode())
    ceremony = passkeys.begin_registration(user)
    added = passkeys.finish_registration(
        user.id, ceremony.challenge_id, device.register(ceremony.options)
    )
    assert added is not None
    return device


@asynccontextmanager
async def passkey_only(ip: str = "198.51.100.10") -> AsyncIterator[httpx.AsyncClient]:
    """A client signed in with the only passkey of a passkey-only account."""
    user = make_user("keys@example.com", password=None)
    device = add_device(user)
    async with https_client(ip) as c:
        assert (await passkey_login(c, device)).status_code == 200
        yield c


@asynccontextmanager
async def with_password(ip: str = "198.51.100.10") -> AsyncIterator[httpx.AsyncClient]:
    """A client signed in with the password of a password-only account."""
    make_user("ana@example.com")
    async with https_client(ip) as c:
        assert (await login(c, "ana@example.com", PASSWORD)).status_code == 200
        yield c


# ---- Set or change the password -----------------------------------------------------------


async def test_a_passkey_only_account_can_set_a_password() -> None:
    async with passkey_only() as c:
        r = await c.post("/api/auth/password", json={"new_password": NEW_PASSWORD})
        assert r.status_code == 200
        assert r.json()["has_password"] is True
        assert (await c.get("/api/auth/me")).json()["has_password"] is True
    async with https_client() as fresh:
        assert (await login(fresh, "keys@example.com", NEW_PASSWORD)).status_code == 200


async def change(c: httpx.AsyncClient, current: str | None, new: str) -> httpx.Response:
    body = {"new_password": new} | ({"current_password": current} if current is not None else {})
    return await c.post("/api/auth/password", json=body)


async def test_change_the_password_with_the_current_one() -> None:
    async with with_password() as c:
        r = await change(c, PASSWORD, NEW_PASSWORD)
        assert r.status_code == 200
    async with https_client() as fresh:
        assert (await login(fresh, "ana@example.com", PASSWORD)).status_code == 401
        assert (await login(fresh, "ana@example.com", NEW_PASSWORD)).status_code == 200


@pytest.mark.parametrize("current", [None, "", "not the password"])
async def test_changing_needs_the_right_current_password(current: str | None) -> None:
    async with with_password() as c:
        r = await change(c, current, NEW_PASSWORD)
        assert r.status_code == 403
        assert r.json()["detail"] == PASSWORD_WRONG
    async with https_client() as fresh:
        assert (await login(fresh, "ana@example.com", PASSWORD)).status_code == 200


@pytest.mark.parametrize("new", ["too short", "unbelievable"])
async def test_a_new_password_that_breaks_the_rules_is_422_with_the_reason(new: str) -> None:
    async with with_password() as c:
        r = await change(c, PASSWORD, new)
        assert r.status_code == 422
        assert r.json()["detail"] == passwords.password_problem(new)
    async with passkey_only() as c:
        r = await change(c, None, new)
        assert r.status_code == 422
        assert r.json()["detail"] == passwords.password_problem(new)
        assert (await c.get("/api/auth/me")).json()["has_password"] is False


async def test_wrong_current_passwords_count_toward_the_sign_in_throttle() -> None:
    """A stolen session mustn't become an unthrottled way to guess the password."""
    async with with_password() as c:
        for _ in range(5):
            assert (await change(c, "not the password", NEW_PASSWORD)).status_code == 403
        r = await change(c, PASSWORD, NEW_PASSWORD)
        assert r.status_code == 429
        assert r.json()["detail"] == LOGIN_THROTTLED
    async with https_client(ip="203.0.113.99") as elsewhere:  # the email is throttled too
        assert (await login(elsewhere, "ana@example.com", PASSWORD)).status_code == 429


async def test_changing_the_password_ends_your_other_sessions_but_not_this_one() -> None:
    async with with_password() as c:
        async with https_client(ip="203.0.113.7") as other:
            assert (await login(other, "ana@example.com", PASSWORD)).status_code == 200
            other_token = other.cookies[SESSION_COOKIE]
            assert (await change(c, PASSWORD, NEW_PASSWORD)).status_code == 200
            assert sessions.resolve(other_token) is None
            assert (await other.get("/api/auth/me")).status_code == 401
        assert (await c.get("/api/auth/me")).status_code == 200


async def test_setting_the_password_needs_a_session() -> None:
    async with https_client() as c:
        assert (await change(c, None, NEW_PASSWORD)).status_code == 401
