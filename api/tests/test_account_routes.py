"""The account page's API (SPEC.md "Marketing and accounts", `/app/account`): set or change
your password (POST /api/auth/password), remove a passkey (DELETE /api/auth/passkeys/{id}),
and sign out everywhere (POST /api/auth/logout-everywhere)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from app.auth import account, passkeys, passwords, sessions, users
from app.auth.deps import SESSION_COOKIE
from app.db import UserRow
from app.schemas import LAST_SIGN_IN_METHOD, LOGIN_THROTTLED, PASSKEY_NOT_FOUND, PASSWORD_WRONG
from tests.test_auth_passkeys import passkey_login
from tests.test_auth_routes import PASSWORD, https_client, login, make_user, set_cookie_header
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


# ---- Remove a passkey ---------------------------------------------------------------------


async def remove(c: httpx.AsyncClient, passkey_id: str, **kwargs: Any) -> httpx.Response:
    return await c.delete(f"/api/auth/passkeys/{passkey_id}", **kwargs)


async def test_remove_a_passkey_when_you_have_a_password() -> None:
    async with with_password() as c:
        user = users.find_by_email("ana@example.com")
        assert user is not None
        device = add_device(user)
        assert (await remove(c, device.id)).status_code == 204
        assert (await c.get("/api/auth/passkeys")).json() == []
    async with https_client() as fresh:
        assert (await passkey_login(fresh, device)).status_code == 401


async def test_remove_one_of_two_passkeys_on_a_passkey_only_account() -> None:
    async with passkey_only() as c:
        user = users.find_by_email("keys@example.com")
        assert user is not None
        second = add_device(user, n=2)
        assert (await remove(c, second.id)).status_code == 204
        [left] = (await c.get("/api/auth/passkeys")).json()
        assert left["id"] != second.id


async def test_you_cant_remove_your_last_sign_in_method() -> None:
    async with passkey_only() as c:
        [only] = (await c.get("/api/auth/passkeys")).json()
        r = await remove(c, only["id"])
        assert r.status_code == 409
        assert r.json()["detail"] == LAST_SIGN_IN_METHOD
        assert len((await c.get("/api/auth/passkeys")).json()) == 1
        # Once there's a password, the same passkey can go.
        assert (await change(c, None, NEW_PASSWORD)).status_code == 200
        assert (await remove(c, only["id"])).status_code == 204


async def test_you_cant_remove_someone_elses_passkey() -> None:
    other = make_user("bo@example.com")
    theirs = add_device(other, n=9)
    async with with_password() as c:
        r = await remove(c, theirs.id)
        assert r.status_code == 404  # the same answer as a passkey that doesn't exist
        assert r.json()["detail"] == PASSKEY_NOT_FOUND
        assert (await remove(c, "no-such-passkey")).status_code == 404
    assert len(passkeys.list_for_user(other.id)) == 1


async def test_removing_a_passkey_needs_a_session_and_the_csrf_header() -> None:
    user = make_user("bo@example.com")
    device = add_device(user)
    async with https_client() as c:
        assert (await remove(c, device.id)).status_code == 401
    async with with_password() as c:
        bare = await remove(c, device.id, headers={"X-Requested-With": ""})
        assert bare.status_code == 403
    assert len(passkeys.list_for_user(user.id)) == 1


async def test_removing_the_last_two_passkeys_at_once_leaves_one() -> None:
    async with passkey_only() as c:
        user = users.find_by_email("keys@example.com")
        assert user is not None
        add_device(user, n=2)
        ids = [p["id"] for p in (await c.get("/api/auth/passkeys")).json()]
        answers = await asyncio.gather(*(remove(c, i) for i in ids))
        assert sorted(r.status_code for r in answers) == [204, 409]
        assert len(passkeys.list_for_user(user.id)) == 1


# ---- Sign out everywhere ------------------------------------------------------------------


async def test_sign_out_everywhere_ends_every_session_including_this_one() -> None:
    async with with_password() as c:
        mine = c.cookies[SESSION_COOKIE]
        async with https_client(ip="203.0.113.7") as other:
            assert (await login(other, "ana@example.com", PASSWORD)).status_code == 200
            r = await c.post("/api/auth/logout-everywhere")
            assert r.status_code == 204
            assert 'tmrx_session=""' in set_cookie_header(r)
            assert sessions.resolve(mine) is None
            assert (await other.get("/api/auth/me")).status_code == 401
        assert (await c.get("/api/auth/me")).status_code == 401
    async with https_client() as fresh:  # the password still works
        assert (await login(fresh, "ana@example.com", PASSWORD)).status_code == 200


async def test_sign_out_everywhere_leaves_other_accounts_signed_in() -> None:
    make_user("bo@example.com")
    async with https_client(ip="203.0.113.7") as bo:
        assert (await login(bo, "bo@example.com", PASSWORD)).status_code == 200
        async with with_password() as c:
            assert (await c.post("/api/auth/logout-everywhere")).status_code == 204
        assert (await bo.get("/api/auth/me")).status_code == 200


async def test_sign_out_everywhere_needs_a_session_and_the_csrf_header() -> None:
    async with https_client() as c:
        assert (await c.post("/api/auth/logout-everywhere")).status_code == 401
    async with with_password() as c:
        bare = await c.post("/api/auth/logout-everywhere", headers={"X-Requested-With": ""})
        assert bare.status_code == 403
        assert (await c.get("/api/auth/me")).status_code == 200


# ---- Races --------------------------------------------------------------------------------


async def test_a_password_set_meanwhile_isnt_overwritten_without_it() -> None:
    """The route decides "set" vs "change" from the account as the request found it. If a
    password appeared since (two tabs setting one at once), the later write is refused with
    the wrong-password answer instead of replacing a password it never checked."""
    user = make_user("keys@example.com", password=None)
    first = account.set_password(
        user.id, passwords.hash_password(PASSWORD), expected=None, keep_session=None
    )
    assert first.password_hash is not None
    with pytest.raises(account.PasswordChangedMeanwhile):
        account.set_password(
            user.id, passwords.hash_password(NEW_PASSWORD), expected=None, keep_session=None
        )
    async with https_client() as c:
        assert (await login(c, "keys@example.com", PASSWORD)).status_code == 200
