"""POST /api/auth/reset/check and POST /api/auth/reset: a link from `make reset-link` sets a new
password once, within an hour, never for a disabled account, and ends the user's sessions."""

import datetime as dt

import httpx
import pytest

from app.auth import passwords, resets, sessions
from app.auth.deps import SESSION_COOKIE
from app.db import SessionRow, UserRow, session_scope, utcnow
from app.schemas import RESET_DISABLED, RESET_EXPIRED, RESET_UNKNOWN, RESET_USED, Me
from tests.test_auth_routes import PASSWORD, disable, https_client, login, make_user

NEW_PASSWORD = "a brand new passphrase"


async def check(c: httpx.AsyncClient, token: str) -> httpx.Response:
    return await c.post("/api/auth/reset/check", json={"token": token})


async def reset(c: httpx.AsyncClient, token: str, password: str = NEW_PASSWORD) -> httpx.Response:
    return await c.post("/api/auth/reset", json={"token": token, "password": password})


def stored_hash(user_id: str) -> str | None:
    with session_scope() as s:
        row = s.get(UserRow, user_id)
        assert row is not None
        return row.password_hash


async def test_a_fresh_link_says_whose_password_it_sets() -> None:
    user = make_user()
    async with https_client() as c:
        r = await check(c, resets.create(user.id))
    assert r.status_code == 200
    assert r.json() == {"email": "ana@example.com"}


async def test_reset_sets_the_password_signs_in_and_ends_other_sessions() -> None:
    user = make_user()
    other_browser = sessions.create(user.id)
    token = resets.create(user.id)
    async with https_client() as c:
        r = await reset(c, token)
        assert r.status_code == 200
        assert Me.model_validate(r.json()).email == "ana@example.com"
        assert (await c.get("/api/auth/me")).json()["id"] == user.id  # signed in here
    assert sessions.resolve(other_browser) is None
    async with https_client() as c:
        assert (await login(c, "ana@example.com", PASSWORD)).status_code == 401
        assert (await login(c, "ana@example.com", NEW_PASSWORD)).status_code == 200


async def test_resetting_ends_the_session_of_the_browser_doing_it_too() -> None:
    user = make_user()
    async with https_client() as c:
        await login(c, "ana@example.com", PASSWORD)
        before = c.cookies[SESSION_COOKIE]
        await reset(c, resets.create(user.id))
        assert c.cookies[SESSION_COOKIE] != before
    assert sessions.resolve(before) is None


async def test_a_link_works_once() -> None:
    user = make_user()
    token = resets.create(user.id)
    async with https_client() as c:
        assert (await reset(c, token)).status_code == 200
        again = await reset(c, token, "yet another passphrase")
        assert again.status_code == 410
        assert again.json()["detail"] == RESET_USED
        assert (await check(c, token)).json()["detail"] == RESET_USED
    assert passwords.verify_password(stored_hash(user.id) or "", NEW_PASSWORD).ok


async def test_using_one_link_retires_the_users_other_links() -> None:
    user = make_user()
    first, second = resets.create(user.id), resets.create(user.id)
    async with https_client() as c:
        assert (await reset(c, second)).status_code == 200
        assert (await reset(c, first, "yet another passphrase")).json()["detail"] == RESET_USED


async def test_a_link_expires_after_an_hour() -> None:
    user = make_user()
    token = resets.create(user.id, now=utcnow() - dt.timedelta(hours=1, seconds=1))
    async with https_client() as c:
        r = await reset(c, token)
        assert r.status_code == 410
        assert r.json()["detail"] == RESET_EXPIRED
        assert (await check(c, token)).json()["detail"] == RESET_EXPIRED
    assert passwords.verify_password(stored_hash(user.id) or "", PASSWORD).ok


async def test_a_link_still_works_just_inside_the_hour() -> None:
    user = make_user()
    token = resets.create(user.id, now=utcnow() - dt.timedelta(minutes=59))
    async with https_client() as c:
        assert (await check(c, token)).status_code == 200


async def test_an_unknown_link_is_not_valid() -> None:
    async with https_client() as c:
        for r in (await check(c, "not-a-token"), await reset(c, "not-a-token")):
            assert r.status_code == 404
            assert r.json()["detail"] == RESET_UNKNOWN


async def test_a_weak_password_is_refused_and_the_link_stays_usable() -> None:
    user = make_user()
    token = resets.create(user.id)
    async with https_client() as c:
        short = await reset(c, token, "too short")
        assert short.status_code == 422
        assert short.json()["detail"] == "Use at least 12 characters."
        common = await reset(c, token, "unbelievable")
        assert common.status_code == 422
        assert "too common" in common.json()["detail"]
        assert SESSION_COOKIE not in c.cookies
        assert (await reset(c, token)).status_code == 200


async def test_a_disabled_user_cant_use_a_link() -> None:
    user = make_user()
    signed_in = sessions.create(user.id)
    token = resets.create(user.id)
    disable(user.id)
    async with https_client() as c:
        r = await reset(c, token)
        assert r.status_code == 403
        assert r.json()["detail"] == RESET_DISABLED
        assert (await check(c, token)).json()["detail"] == RESET_DISABLED
        assert SESSION_COOKIE not in c.cookies
    assert passwords.verify_password(stored_hash(user.id) or "", PASSWORD).ok
    with session_scope() as s:  # nothing was ended or claimed on the way to refusing
        assert s.get(SessionRow, sessions.token_hash(signed_in)) is not None


async def test_no_session_for_an_account_disabled_mid_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    real_redeem = resets.redeem

    def redeem_then_disable(token: str, password: str) -> UserRow:
        redeemed = real_redeem(token, password)
        disable(user.id)  # `make disable-user` lands between the redeem and the sign-in
        return redeemed

    monkeypatch.setattr(resets, "redeem", redeem_then_disable)
    async with https_client() as c:
        r = await reset(c, resets.create(user.id))
        assert r.status_code == 403
        assert r.json()["detail"] == RESET_DISABLED
        assert SESSION_COOKIE not in c.cookies


async def test_a_passkey_only_account_can_set_its_first_password() -> None:
    user = make_user("pat@example.com", password=None)
    async with https_client() as c:
        r = await reset(c, resets.create(user.id))
        assert r.status_code == 200
        assert r.json()["has_password"] is True


async def test_reset_needs_the_csrf_header() -> None:
    user = make_user()
    token = resets.create(user.id)
    async with https_client() as c:
        r = await c.post(
            "/api/auth/reset",
            json={"token": token, "password": NEW_PASSWORD},
            headers={"X-Requested-With": ""},
        )
    assert r.status_code == 403
