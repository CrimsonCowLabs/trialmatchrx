"""Adding a passkey on the invite page: POST /api/auth/invites/{token}/passkey/options starts
registration for the account the invite will create, and POST .../accept takes a passkey, a
password, or both (SPEC.md "Marketing and accounts": "the person adds a passkey, sets a
password, or both"). The account, its passkey and the spent invite are written together, so
an account never ends up with no way to sign in."""

import datetime as dt
from typing import Any

import httpx
from sqlmodel import select

from app.auth import invites, users
from app.db import PasskeyRow, session_scope
from app.schemas import (
    INVITE_EXPIRED,
    INVITE_NEEDS_SIGN_IN,
    INVITE_UNKNOWN,
    INVITE_USED,
    PASSKEY_NOT_ADDED,
    Me,
)
from tests.test_auth_passkeys import add_passkey, passkey_login, signed_in
from tests.test_invite_routes import PASSWORD, https_client
from tests.webauthn_fake import FakeAuthenticator


async def passkey_options(c: httpx.AsyncClient, token: str) -> httpx.Response:
    return await c.post(f"/api/auth/invites/{token}/passkey/options")


async def accept_with(
    c: httpx.AsyncClient,
    token: str,
    device: FakeAuthenticator | None,
    password: str | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Accept the invite with `device` as its passkey (registered now) and/or `password`."""
    body: dict[str, Any] = {"password": password}
    if device is not None:
        begun = await passkey_options(c, token)
        assert begun.status_code == 200
        b = begun.json()
        body["passkey"] = {
            "challenge_id": b["challenge_id"],
            "credential": device.register(b["options"], **kwargs),
        }
    return await c.post(f"/api/auth/invites/{token}/accept", json=body)


def passkey_count() -> int:
    with session_scope() as s:
        return len(s.exec(select(PasskeyRow)).all())


async def test_a_passkey_instead_of_a_password() -> None:
    issued = invites.create("ana@example.com")
    device = FakeAuthenticator()
    async with https_client() as c:
        begun = (await passkey_options(c, issued.token)).json()
        assert begun["options"]["user"]["name"] == "ana@example.com"
        r = await accept_with(c, issued.token, device)
        assert r.status_code == 200
        me = Me.model_validate(r.json())
        assert me.email == "ana@example.com"
        assert me.has_password is False
        # Signed in, with the passkey on the account.
        [listed] = (await c.get("/api/auth/passkeys")).json()
        assert listed["id"] == device.id
    async with https_client() as c:  # and it signs in later
        assert (await passkey_login(c, device)).status_code == 200
    async with https_client() as c:  # the link is spent
        assert (await accept_with(c, issued.token, None, PASSWORD)).status_code == 410


async def test_a_passkey_and_a_password() -> None:
    issued = invites.create("ana@example.com")
    async with https_client() as c:
        r = await accept_with(c, issued.token, FakeAuthenticator(), PASSWORD)
        assert r.status_code == 200
        assert r.json()["has_password"] is True
        assert len((await c.get("/api/auth/passkeys")).json()) == 1


async def test_neither_creates_nothing_and_keeps_the_link() -> None:
    issued = invites.create("ana@example.com")
    async with https_client() as c:
        r = await accept_with(c, issued.token, None)
        assert r.status_code == 400
        assert r.json() == {"detail": INVITE_NEEDS_SIGN_IN}
    assert users.find_by_email("ana@example.com") is None
    invites.lookup(issued.token)  # still usable


async def test_a_bad_passkey_creates_nothing_and_keeps_the_link() -> None:
    issued = invites.create("ana@example.com")
    async with https_client() as c:
        for bad in (FakeAuthenticator(origin="https://evil.example"), FakeAuthenticator()):
            kwargs = {"verified": False} if bad.origin.endswith("3045") else {}
            r = await accept_with(c, issued.token, bad, PASSWORD, **kwargs)
            assert r.status_code == 400
            assert r.json() == {"detail": PASSKEY_NOT_ADDED}
    assert users.find_by_email("ana@example.com") is None
    assert passkey_count() == 0
    invites.lookup(issued.token)


async def test_a_password_that_breaks_the_rules_creates_nothing() -> None:
    issued = invites.create("ana@example.com")
    async with https_client() as c:
        r = await accept_with(c, issued.token, FakeAuthenticator(), "short")
        assert r.status_code == 422
    assert users.find_by_email("ana@example.com") is None
    assert passkey_count() == 0


async def test_one_invites_challenge_cant_finish_another() -> None:
    ana = invites.create("ana@example.com")
    bo = invites.create("bo@example.com")
    device = FakeAuthenticator()
    async with https_client() as c:
        b = (await passkey_options(c, ana.token)).json()
        r = await c.post(
            f"/api/auth/invites/{bo.token}/accept",
            json={
                "password": None,
                "passkey": {
                    "challenge_id": b["challenge_id"],
                    "credential": device.register(b["options"]),
                },
            },
        )
        assert r.status_code == 400
    assert users.find_by_email("bo@example.com") is None
    assert passkey_count() == 0


async def test_an_account_page_challenge_cant_finish_an_invite() -> None:
    issued = invites.create("bo@example.com")
    device = FakeAuthenticator()
    async with signed_in() as c:
        b = (await c.post("/api/auth/passkey/register/options")).json()
        r = await c.post(
            f"/api/auth/invites/{issued.token}/accept",
            json={
                "password": None,
                "passkey": {
                    "challenge_id": b["challenge_id"],
                    "credential": device.register(b["options"]),
                },
            },
        )
        assert r.status_code == 400
    assert users.find_by_email("bo@example.com") is None


async def test_an_invite_challenge_cant_add_a_passkey_to_a_signed_in_account() -> None:
    issued = invites.create("bo@example.com")
    device = FakeAuthenticator()
    async with signed_in() as c:
        b = (await passkey_options(c, issued.token)).json()
        r = await c.post(
            "/api/auth/passkey/register/verify",
            json={"challenge_id": b["challenge_id"], "credential": device.register(b["options"])},
        )
        assert r.status_code == 400
        assert (await c.get("/api/auth/passkeys")).json() == []


async def test_a_passkey_already_on_an_account_creates_nothing() -> None:
    first = invites.create("ana@example.com")
    second = invites.create("bo@example.com")
    device = FakeAuthenticator()
    async with https_client() as c:
        assert (await accept_with(c, first.token, device)).status_code == 200
    async with https_client() as c:
        r = await accept_with(c, second.token, device)  # the same credential id again
        assert r.status_code == 400
        assert r.json() == {"detail": PASSKEY_NOT_ADDED}
    assert users.find_by_email("bo@example.com") is None
    invites.lookup(second.token)  # still usable


async def test_passkey_options_refuse_a_link_that_cant_be_used() -> None:
    used = invites.create("used@example.com")
    expired = invites.create("old@example.com", now=dt.datetime.now(dt.UTC) - dt.timedelta(days=8))
    async with https_client() as c:
        assert (await accept_with(c, used.token, None, PASSWORD)).status_code == 200
    async with https_client() as c:
        for token, status, detail in [
            (used.token, 410, INVITE_USED),
            (expired.token, 410, INVITE_EXPIRED),
            ("nope", 404, INVITE_UNKNOWN),
        ]:
            r = await passkey_options(c, token)
            assert (r.status_code, r.json()) == (status, {"detail": detail})


async def test_a_signed_in_account_can_still_add_more_passkeys() -> None:
    """The passkey made on the invite page is excluded when adding another from the account."""
    issued = invites.create("ana@example.com")
    first, second = FakeAuthenticator(), FakeAuthenticator(credential_id=b"second")
    async with https_client() as c:
        assert (await accept_with(c, issued.token, first)).status_code == 200
        options = (await c.post("/api/auth/passkey/register/options")).json()["options"]
        assert [x["id"] for x in options["excludeCredentials"]] == [first.id]
        assert (await add_passkey(c, second)).status_code == 201
