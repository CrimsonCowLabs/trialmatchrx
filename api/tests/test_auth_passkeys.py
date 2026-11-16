"""Passkeys over HTTP: add one while signed in (POST /api/auth/passkey/register/*), list them
(GET /api/auth/passkeys), and sign in with one (POST /api/auth/passkey/login/*). The browser
side is `FakeAuthenticator`, a software authenticator with a fixture key."""

import datetime as dt
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from app.auth import passkeys, sessions, throttle, users
from app.auth.deps import SESSION_COOKIE
from app.config import get_settings
from app.schemas import LOGIN_FAILED, LOGIN_THROTTLED, PASSKEY_NOT_ADDED, Me, PasskeyInfo
from tests.test_auth_routes import PASSWORD, disable, https_client, login, make_user
from tests.webauthn_fake import FakeAuthenticator

PROD_HOST = "tmrx.crimsoncowlabs.com"


@pytest.fixture
def prod_webauthn() -> Iterator[None]:
    settings = get_settings()
    original = settings.webauthn_rp_id, settings.webauthn_origin
    settings.webauthn_rp_id, settings.webauthn_origin = PROD_HOST, f"https://{PROD_HOST}"
    yield
    settings.webauthn_rp_id, settings.webauthn_origin = original


@asynccontextmanager
async def signed_in(
    email: str = "ana@example.com", ip: str = "198.51.100.10"
) -> AsyncIterator[httpx.AsyncClient]:
    """A client signed in with a password as a new user `email`."""
    make_user(email)
    async with https_client(ip) as c:
        assert (await login(c, email, PASSWORD)).status_code == 200
        yield c


async def add_passkey(
    c: httpx.AsyncClient, device: FakeAuthenticator, **kwargs: Any
) -> httpx.Response:
    begun = await c.post("/api/auth/passkey/register/options")
    assert begun.status_code == 200
    body = begun.json()
    return await c.post(
        "/api/auth/passkey/register/verify",
        json={
            "challenge_id": body["challenge_id"],
            "credential": device.register(body["options"], **kwargs),
        },
    )


async def test_add_a_passkey_and_list_it() -> None:
    device = FakeAuthenticator()
    async with signed_in() as c:
        added = await add_passkey(c, device)
        assert added.status_code == 201
        info = PasskeyInfo.model_validate(added.json())
        assert info.id == device.id
        assert info.last_used_at is None

        listed = await c.get("/api/auth/passkeys")
        assert listed.status_code == 200
        assert [PasskeyInfo.model_validate(p) for p in listed.json()] == [info]


async def test_adding_or_listing_passkeys_needs_a_session() -> None:
    async with https_client() as c:
        assert (await c.post("/api/auth/passkey/register/options")).status_code == 401
        r = await c.post(
            "/api/auth/passkey/register/verify", json={"challenge_id": "x", "credential": {}}
        )
        assert r.status_code == 401
        assert (await c.get("/api/auth/passkeys")).status_code == 401


async def test_registration_options_ask_for_a_discoverable_verified_passkey() -> None:
    first = FakeAuthenticator()
    async with signed_in() as c:
        await add_passkey(c, first)
        options = (await c.post("/api/auth/passkey/register/options")).json()["options"]
    user = users.find_by_email("ana@example.com")
    assert user is not None
    assert options["rp"] == {"id": "localhost", "name": "TrialMatch Rx"}
    assert options["user"]["name"] == "ana@example.com"
    assert options["user"]["id"] != "ana@example.com"  # opaque handle, not the email
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    # The device that already has a passkey here isn't asked to make a second one.
    assert [c["id"] for c in options["excludeCredentials"]] == [first.id]


@pytest.mark.parametrize(
    "change",
    [{"origin": "https://evil.example"}, {"rp_id": "evil.example"}],
    ids=["phishing origin", "other relying party"],
)
async def test_a_bad_registration_stores_nothing(change: dict[str, str]) -> None:
    device = FakeAuthenticator(**change)  # type: ignore[arg-type]
    async with signed_in() as c:
        r = await add_passkey(c, device)
        assert r.status_code == 400
        assert r.json() == {"detail": PASSKEY_NOT_ADDED}
        assert (await c.get("/api/auth/passkeys")).json() == []


async def test_a_registration_without_user_verification_stores_nothing() -> None:
    async with signed_in() as c:
        assert (await add_passkey(c, FakeAuthenticator(), verified=False)).status_code == 400
        assert (await c.get("/api/auth/passkeys")).json() == []


async def test_one_users_challenge_cant_add_a_passkey_to_another() -> None:
    device = FakeAuthenticator()
    async with signed_in("ana@example.com") as ana:
        body = (await ana.post("/api/auth/passkey/register/options")).json()
        async with signed_in("bo@example.com", ip="198.51.100.11") as bo:
            r = await bo.post(
                "/api/auth/passkey/register/verify",
                json={
                    "challenge_id": body["challenge_id"],
                    "credential": device.register(body["options"]),
                },
            )
            assert r.status_code == 400
            assert (await bo.get("/api/auth/passkeys")).json() == []
        assert (await ana.get("/api/auth/passkeys")).json() == []


async def test_rp_id_and_origin_come_from_settings(prod_webauthn: None) -> None:
    device = FakeAuthenticator(origin="https://tmrx.crimsoncowlabs.com", rp_id=PROD_HOST)
    await registered(device)
    async with https_client() as c:
        options = (await c.post("/api/auth/passkey/login/options")).json()["options"]
        assert options["rpId"] == PROD_HOST
        assert options["userVerification"] == "required"
        assert "allowCredentials" not in options or options["allowCredentials"] == []
        assert (await passkey_login(c, device)).status_code == 200
        # The same passkey answering for the dev domain fails here.
        dev = FakeAuthenticator(credential_id=device.credential_id, sign_count=10)
        dev.user_handle = device.user_handle
        assert (await passkey_login(c, dev)).status_code == 401


async def registered(device: FakeAuthenticator, email: str = "ana@example.com") -> None:
    """`email` gets an account (with a password) and `device` as its passkey."""
    async with signed_in(email, ip="198.51.100.200") as c:
        assert (await add_passkey(c, device)).status_code == 201


async def passkey_login(
    c: httpx.AsyncClient, device: FakeAuthenticator | None, **kwargs: Any
) -> httpx.Response:
    """Sign in with `device`; None plays a cancelled prompt."""
    begun = await c.post("/api/auth/passkey/login/options")
    assert begun.status_code == 200
    body = begun.json()
    credential = device.sign_in(body["options"], **kwargs) if device is not None else None
    return await c.post(
        "/api/auth/passkey/login/verify",
        json={"challenge_id": body["challenge_id"], "credential": credential},
    )


async def test_sign_in_with_a_passkey() -> None:
    device = FakeAuthenticator()
    await registered(device)
    async with https_client() as c:
        r = await passkey_login(c, device)
        assert r.status_code == 200
        assert Me.model_validate(r.json()).email == "ana@example.com"
        assert sessions.resolve(c.cookies[SESSION_COOKIE]) is not None
        assert (await c.get("/api/auth/me")).json()["email"] == "ana@example.com"
        [info] = (await c.get("/api/auth/passkeys")).json()
        assert info["last_used_at"] is not None
    user = users.find_by_email("ana@example.com")
    assert user is not None and user.last_login_at is not None


async def test_a_passkey_only_account_can_sign_in() -> None:
    """The invite page (#3) can make an account with no password; its passkey is enough."""
    user = make_user("keys@example.com", password=None)
    device = FakeAuthenticator()
    ceremony = passkeys.begin_registration(user)
    added = passkeys.finish_registration(
        user.id, ceremony.challenge_id, device.register(ceremony.options)
    )
    assert added is not None
    async with https_client() as c:
        r = await passkey_login(c, device)
    assert r.status_code == 200
    assert r.json()["has_password"] is False


def _device(n: int, **kwargs: Any) -> FakeAuthenticator:
    return FakeAuthenticator(credential_id=f"fake-credential-{n}".encode(), **kwargs)


async def test_every_passkey_failure_gives_the_password_failure_answer() -> None:
    """Cancelled, unknown passkey, phishing origin, other relying party, wrong key, no user
    verification, a disabled account: each is the shared 401 and no session."""
    answers: list[tuple[int, Any]] = []

    async def attempt(n: int, device: FakeAuthenticator | None, **kwargs: Any) -> None:
        async with https_client(ip=f"198.51.100.{n + 20}") as c:
            r = await passkey_login(c, device, **kwargs)
            assert SESSION_COOKIE not in c.cookies
            answers.append((r.status_code, r.json()))

    await attempt(0, None)  # cancelled
    await attempt(1, _device(1))  # never registered
    for n, change in enumerate(
        [
            {"origin": "https://tmrx.crimsoncowlabs.com.evil.example"},
            {"rp_id": "evil.example"},
            {"key_name": "authenticator_b"},  # right credential id, wrong private key
        ],
        start=2,
    ):
        device = _device(n)
        await registered(device, f"user{n}@example.com")
        for attr, value in change.items():
            setattr(device, attr, value)
        await attempt(n, device)
    unverified = _device(5)
    await registered(unverified, "user5@example.com")
    await attempt(5, unverified, verified=False)
    off = _device(6)
    await registered(off, "off@example.com")
    found = users.find_by_email("off@example.com")
    assert found is not None
    disable(found.id)
    await attempt(6, off)

    assert answers == [(401, {"detail": LOGIN_FAILED})] * 7


async def test_a_user_handle_for_another_account_fails() -> None:
    """The signature doesn't cover userHandle, so it's checked against the passkey's owner."""
    ana, bo = _device(1), _device(2)
    await registered(ana, "ana@example.com")
    await registered(bo, "bo@example.com")
    ana.user_handle = bo.user_handle
    async with https_client() as c:
        assert (await passkey_login(c, ana)).status_code == 401


async def test_a_challenge_is_single_use() -> None:
    device = FakeAuthenticator()
    await registered(device)
    async with https_client() as c:
        body = (await c.post("/api/auth/passkey/login/options")).json()
        credential = device.sign_in(body["options"])
        verify = {"challenge_id": body["challenge_id"], "credential": credential}
        assert (await c.post("/api/auth/passkey/login/verify", json=verify)).status_code == 200
    async with https_client() as c:  # replaying the same signed response
        r = await c.post("/api/auth/passkey/login/verify", json=verify)
        assert r.status_code == 401
        assert SESSION_COOKIE not in c.cookies


async def test_an_expired_challenge_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    device = FakeAuthenticator()
    await registered(device)
    monkeypatch.setattr(passkeys, "CHALLENGE_TTL", dt.timedelta(0))
    async with https_client() as c:
        assert (await passkey_login(c, device)).status_code == 401


async def test_outstanding_challenges_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting a sign-in needs no session; past the cap the oldest challenges are dropped."""
    device = FakeAuthenticator()
    await registered(device)
    monkeypatch.setattr(passkeys, "MAX_CHALLENGES", 2)
    async with https_client() as c:
        oldest = (await c.post("/api/auth/passkey/login/options")).json()
        for _ in range(2):
            assert (await c.post("/api/auth/passkey/login/options")).status_code == 200
        r = await c.post(
            "/api/auth/passkey/login/verify",
            json={
                "challenge_id": oldest["challenge_id"],
                "credential": device.sign_in(oldest["options"]),
            },
        )
        assert r.status_code == 401
        assert (await passkey_login(c, device)).status_code == 200  # newer ones still work


async def test_the_same_passkey_cant_be_added_twice() -> None:
    device = FakeAuthenticator()
    async with signed_in() as c:
        assert (await add_passkey(c, device)).status_code == 201
        assert (await add_passkey(c, device)).status_code == 400
        assert len((await c.get("/api/auth/passkeys")).json()) == 1


async def test_passkey_failures_count_toward_the_ip_throttle() -> None:
    device = FakeAuthenticator()
    await registered(device)
    async with https_client(ip="203.0.113.7") as c:
        for _ in range(throttle.MAX_FAILURES):
            assert (await passkey_login(c, None)).status_code == 401  # cancelled
        r = await passkey_login(c, device)  # now even the right passkey waits
        assert r.status_code == 429
        assert r.json() == {"detail": LOGIN_THROTTLED}
        # ...and so does a password from that IP: it's one throttle.
        assert (await login(c, "ana@example.com", PASSWORD)).status_code == 429


async def test_password_failures_throttle_that_accounts_passkey() -> None:
    device = FakeAuthenticator()
    await registered(device)
    for n in range(throttle.MAX_FAILURES):
        async with https_client(ip=f"203.0.113.{n + 10}") as c:
            assert (await login(c, "ana@example.com", "wrong horse battery")).status_code == 401
    async with https_client(ip="203.0.113.99") as c:
        assert (await passkey_login(c, device)).status_code == 429


async def test_bad_passkey_attempts_count_against_the_owners_email() -> None:
    device = FakeAuthenticator()
    await registered(device)
    device.origin = "https://evil.example"
    for n in range(throttle.MAX_FAILURES):
        async with https_client(ip=f"203.0.113.{n + 10}") as c:
            assert (await passkey_login(c, device)).status_code == 401
    async with https_client(ip="203.0.113.99") as c:
        assert (await login(c, "ana@example.com", PASSWORD)).status_code == 429


async def test_unknown_passkeys_from_many_ips_dont_throttle_anyone_else() -> None:
    """A failure with no known account counts against its IP only, not a shared bucket."""
    for n in range(throttle.MAX_FAILURES + 1):
        async with https_client(ip=f"203.0.113.{n + 10}") as c:
            assert (await passkey_login(c, None)).status_code == 401
    device = FakeAuthenticator()
    await registered(device)
    async with https_client(ip="203.0.113.99") as c:
        assert (await passkey_login(c, device)).status_code == 200
