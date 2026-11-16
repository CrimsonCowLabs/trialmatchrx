"""GET /api/auth/invites/{token} and POST /api/auth/invites/{token}/accept: the invite page
reads who it's for, then sets a password, which creates the account and signs it in. An
expired, used or unknown link (or an email that has an account by now) is refused with a clear
message and creates nothing."""

import asyncio
import datetime as dt
from typing import Any

import httpx
import pytest
from sqlmodel import select

from app.auth import invites, passwords, sessions, users
from app.auth.deps import SESSION_COOKIE
from app.db import InviteRow, session_scope, utcnow
from app.main import app
from app.schemas import (
    INVITE_ACCOUNT_EXISTS,
    INVITE_EXPIRED,
    INVITE_UNKNOWN,
    INVITE_USED,
    InviteInfo,
    Me,
)

PASSWORD = "correct horse battery"
CSRF = {"X-Requested-With": "fetch"}


def https_client() -> httpx.AsyncClient:
    """Over https, like prod, so the Secure session cookie is kept and sent back."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test", headers=CSRF
    )


async def accept(c: httpx.AsyncClient, token: str, password: str = PASSWORD) -> httpx.Response:
    return await c.post(f"/api/auth/invites/{token}/accept", json={"password": password})


def invite_count() -> int:
    with session_scope() as s:
        return len(s.exec(select(InviteRow)).all())


async def test_the_page_reads_who_the_invite_is_for() -> None:
    issued = invites.create("Ana@Example.com")
    async with https_client() as c:
        r = await c.get(f"/api/auth/invites/{issued.token}")
    assert r.status_code == 200
    info = InviteInfo.model_validate(r.json())
    assert info.email == "ana@example.com"
    assert info.expires_at == issued.expires_at


async def test_setting_a_password_creates_the_account_and_signs_in() -> None:
    issued = invites.create("ana@example.com")
    async with https_client() as c:
        r = await accept(c, issued.token)
        assert r.status_code == 200
        me = Me.model_validate(r.json())
        assert me.email == "ana@example.com" and me.has_password
        assert c.cookies.get(SESSION_COOKIE)
        assert (await c.get("/api/auth/me")).json()["id"] == me.id
        # ...and the password works for signing in later.
        login = await c.post(
            "/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD}
        )
        assert login.status_code == 200


async def test_a_used_link_is_refused_and_creates_nothing() -> None:
    issued = invites.create("ana@example.com")
    async with https_client() as c:
        assert (await accept(c, issued.token)).status_code == 200
    async with https_client() as c:
        page = await c.get(f"/api/auth/invites/{issued.token}")
        again = await accept(c, issued.token, "another long password")
        assert not c.cookies.get(SESSION_COOKIE)
    assert page.status_code == 410 and page.json()["detail"] == INVITE_USED
    assert again.status_code == 410 and again.json()["detail"] == INVITE_USED
    user = users.find_by_email("ana@example.com")
    assert user is not None and user.password_hash is not None
    assert passwords.verify_password(user.password_hash, PASSWORD).ok  # not overwritten


async def test_an_expired_link_is_refused_and_creates_nothing() -> None:
    issued = invites.create("ana@example.com", now=utcnow() - dt.timedelta(days=7, seconds=1))
    async with https_client() as c:
        page = await c.get(f"/api/auth/invites/{issued.token}")
        r = await accept(c, issued.token)
    assert page.status_code == 410 and page.json()["detail"] == INVITE_EXPIRED
    assert r.status_code == 410 and r.json()["detail"] == INVITE_EXPIRED
    assert users.find_by_email("ana@example.com") is None


async def test_a_link_still_works_just_before_seven_days() -> None:
    issued = invites.create("ana@example.com", now=utcnow() - dt.timedelta(days=6, hours=23))
    async with https_client() as c:
        assert (await accept(c, issued.token)).status_code == 200


async def test_an_unknown_link_is_refused_and_creates_nothing() -> None:
    async with https_client() as c:
        page = await c.get("/api/auth/invites/not-a-real-token")
        r = await accept(c, "not-a-real-token")
    assert page.status_code == 404 and page.json()["detail"] == INVITE_UNKNOWN
    assert r.status_code == 404 and r.json()["detail"] == INVITE_UNKNOWN
    assert invite_count() == 0


async def test_an_email_that_got_an_account_since_is_refused() -> None:
    issued = invites.create("ana@example.com")
    users.create_user("ana@example.com", password_hash=None)  # e.g. a second invite accepted
    async with https_client() as c:
        page = await c.get(f"/api/auth/invites/{issued.token}")
        r = await accept(c, issued.token)
    assert page.status_code == 409 and page.json()["detail"] == INVITE_ACCOUNT_EXISTS
    assert r.status_code == 409 and r.json()["detail"] == INVITE_ACCOUNT_EXISTS


async def test_a_password_that_breaks_the_rules_keeps_the_link_usable() -> None:
    issued = invites.create("ana@example.com")
    async with https_client() as c:
        short = await accept(c, issued.token, "too short")
        common = await accept(c, issued.token, "unbelievable")
        assert short.status_code == 422
        assert short.json()["detail"] == passwords.password_problem("too short")
        assert common.status_code == 422
        assert common.json()["detail"] == passwords.password_problem("unbelievable")
        assert users.find_by_email("ana@example.com") is None
        assert (await accept(c, issued.token)).status_code == 200


async def test_two_requests_racing_on_one_link_make_one_account() -> None:
    issued = invites.create("ana@example.com")
    async with https_client() as a, https_client() as b:
        results = await asyncio.gather(accept(a, issued.token), accept(b, issued.token))
    assert sorted(r.status_code for r in results) == [200, 410]


async def test_accepting_needs_the_csrf_header() -> None:
    issued = invites.create("ana@example.com")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as c:
        r = await accept(c, issued.token)
    assert r.status_code == 403
    assert users.find_by_email("ana@example.com") is None


async def test_a_new_invite_cancels_the_older_unused_ones() -> None:
    first = invites.create("ana@example.com")
    other = invites.create("bea@example.com")
    second = invites.create("ana@example.com")
    async with https_client() as c:
        old = await accept(c, first.token)
        assert old.status_code == 410 and old.json()["detail"] == INVITE_EXPIRED
        assert users.find_by_email("ana@example.com") is None
        assert (await accept(c, second.token)).status_code == 200
        assert (await accept(c, other.token, "a third long password")).status_code == 200


def test_losing_the_race_on_the_email_is_account_exists_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other invite's account lands after this one's check but before its insert."""
    issued = invites.create("ana@example.com")
    usable = invites._usable

    def check_then_lose(*args: Any) -> InviteRow:
        row = usable(*args)
        users.create_user("ana@example.com", password_hash=None)
        return row

    monkeypatch.setattr(invites, "_usable", check_then_lose)
    with pytest.raises(invites.AlreadyHasAccount):
        invites.accept(issued.token, password_hash=passwords.hash_password(PASSWORD))
    monkeypatch.undo()
    with session_scope() as s:  # rolled back: the invite is still unspent
        row = s.get(InviteRow, sessions.token_hash(issued.token))
        assert row is not None and row.used_at is None
