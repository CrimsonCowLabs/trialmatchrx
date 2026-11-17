"""POST /api/access-requests (SPEC.md "Marketing and accounts", Request access) and
`make access-requests` (scripts/access_requests.py), which is how a stored request is seen.
The ASGI client's peer is 127.0.0.1 (a trusted proxy), so a test picks its IP with
X-Forwarded-For."""

import datetime as dt
from typing import Any

import httpx
import pytest

from app import access_requests
from app.config import get_settings
from app.emails.sender import SendResult
from app.main import app
from app.schemas import ACCESS_REQUESTS_THROTTLED, AccessRequestCreate
from scripts.access_requests import main as list_requests
from tests.email_fake import FakeSender

CSRF = {"X-Requested-With": "fetch"}
T0 = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.UTC)
MINUTE = dt.timedelta(minutes=1)


def client(ip: str = "198.51.100.20") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={**CSRF, "X-Forwarded-For": ip},
    )


def form(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Ana Silva",
        "email": "ana@acme-pharma.example",
        "organization": "Acme Pharma",
        "role": "sponsor",
        "message": "We run two T2D trials.",
        **overrides,
    }


def listed(capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert list_requests([]) == 0
    return capsys.readouterr().out.splitlines()


async def test_a_request_is_stored_and_listed(capsys: pytest.CaptureFixture[str]) -> None:
    async with client() as c:
        sent = await c.post("/api/access-requests", json=form())
    assert sent.status_code == 204
    out = "\n".join(listed(capsys))
    for value in ("Ana Silva", "ana@acme-pharma.example", "Acme Pharma", "sponsor"):
        assert value in out
    assert "We run two T2D trials." in out


async def test_a_filled_honeypot_gets_the_same_answer_and_stores_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with client() as c:
        sent = await c.post("/api/access-requests", json=form(website="https://spam.example"))
    assert sent.status_code == 204
    assert sent.content == b""
    assert listed(capsys) == ["no access requests"]


async def test_the_fourth_request_in_an_hour_from_one_ip_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with client("198.51.100.30") as c:
        for n in range(3):
            sent = await c.post("/api/access-requests", json=form(name=f"Person {n}"))
            assert sent.status_code == 204
        fourth = await c.post("/api/access-requests", json=form(name="Person 3"))
    assert fourth.status_code == 429
    assert fourth.json() == {"detail": ACCESS_REQUESTS_THROTTLED}
    out = "\n".join(listed(capsys))
    assert "Person 2" in out
    assert "Person 3" not in out


async def test_the_limit_is_per_ip() -> None:
    async with client("198.51.100.31") as c:
        for _ in range(3):
            await c.post("/api/access-requests", json=form())
    async with client("198.51.100.32") as other:
        sent = await other.post("/api/access-requests", json=form())
    assert sent.status_code == 204


async def test_honeypot_hits_dont_count_toward_the_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with client() as c:
        for _ in range(5):
            await c.post("/api/access-requests", json=form(website="x"))
        sent = await c.post("/api/access-requests", json=form(name="Real Person"))
    assert sent.status_code == 204
    assert "Real Person" in "\n".join(listed(capsys))


async def test_needs_no_session_but_does_need_the_csrf_header() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as anonymous:
        refused = await anonymous.post("/api/access-requests", json=form())
        sent = await anonymous.post("/api/access-requests", json=form(), headers=CSRF)
    assert refused.status_code == 403
    assert sent.status_code == 204


@pytest.mark.parametrize(
    "overrides",
    [
        {"role": "investor"},
        {"email": "not-an-email"},
        {"email": "ana@localhost"},
        {"name": "   "},
        {"organization": ""},
        {"name": "x" * 201},
        {"organization": "x" * 201},
        {"email": f"{'a' * 320}@acme.example"},
        {"message": "x" * 2001},
    ],
)
async def test_invalid_fields_are_refused(
    overrides: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    async with client() as c:
        sent = await c.post("/api/access-requests", json=form(**overrides))
    assert sent.status_code == 422
    assert listed(capsys) == ["no access requests"]


@pytest.mark.parametrize("field", ["name", "email", "organization", "role"])
async def test_required_fields(field: str) -> None:
    body = form()
    del body[field]
    async with client() as c:
        sent = await c.post("/api/access-requests", json=body)
    assert sent.status_code == 422


async def test_the_message_is_optional_and_fields_are_trimmed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with client() as c:
        without = form(name="  Bo Chen  ", role="cro")
        del without["message"]
        assert (await c.post("/api/access-requests", json=without)).status_code == 204
        blank = form(name="Cy Diaz", message="   ")
        assert (await c.post("/api/access-requests", json=blank)).status_code == 204
    lines = listed(capsys)
    assert len(lines) == 3  # header + two requests, neither with a message line
    assert any(line.split()[2:4] == ["Bo", "Chen"] for line in lines[1:])


def test_lists_newest_first_with_the_message_below(capsys: pytest.CaptureFixture[str]) -> None:
    older = AccessRequestCreate.model_validate(
        form(name="Old Person", role="site", message="First line.\nSecond line.")
    )
    newer = AccessRequestCreate.model_validate(form(name="New Person", message=None))
    access_requests.submit(older, "203.0.113.6", now=T0)
    access_requests.submit(newer, "203.0.113.7", now=T0 + MINUTE)

    lines = listed(capsys)
    assert lines[0].split() == ["RECEIVED", "NAME", "EMAIL", "ORGANIZATION", "ROLE"]
    assert lines[1].split() == [
        "2026-11-16",
        "12:01",
        "New",
        "Person",
        "ana@acme-pharma.example",
        "Acme",
        "Pharma",
        "sponsor",
    ]
    assert lines[2].split()[:4] == ["2026-11-16", "12:00", "Old", "Person"]
    assert lines[2].split()[-1] == "site"
    assert lines[3] == "    First line. Second line."
    assert len(lines) == 4


def test_the_limit_lifts_an_hour_after_a_request() -> None:
    body = AccessRequestCreate.model_validate(form())
    for minute in range(3):
        assert access_requests.submit(body, "203.0.113.5", now=T0 + minute * MINUTE) == "stored"
    assert access_requests.submit(body, "203.0.113.5", now=T0 + 59 * MINUTE) == "throttled"
    # The first one is now an hour old, so one slot is free again.
    assert access_requests.submit(body, "203.0.113.5", now=T0 + 60 * MINUTE) == "stored"
    assert access_requests.submit(body, "203.0.113.5", now=T0 + 60 * MINUTE) == "throttled"


@pytest.fixture
def notify(monkeypatch: pytest.MonkeyPatch) -> str:
    """ADMIN_NOTIFY_EMAIL set, and a known APP_URL for the admin link."""
    monkeypatch.setattr(get_settings(), "admin_notify_email", "admin@tm.example")
    monkeypatch.setattr(get_settings(), "app_url", "https://tmrx.example/")
    return "admin@tm.example"


async def test_a_stored_request_emails_the_admin_with_reply_to_the_requester(
    notify: str, fake_sender: FakeSender
) -> None:
    async with client() as c:
        sent = await c.post("/api/access-requests", json=form())
    assert sent.status_code == 204
    (email,) = fake_sender.outbox
    assert email.to == notify
    assert email.reply_to == "ana@acme-pharma.example"
    assert email.subject == "Access request: Ana Silva (Acme Pharma)"
    for value in ("Ana Silva", "ana@acme-pharma.example", "Acme Pharma", "sponsor"):
        assert value in email.text and value in email.html
    assert "We run two T2D trials." in email.text
    assert "https://tmrx.example/app/admin" in email.text


async def test_without_a_notify_address_no_email_is_sent(
    fake_sender: FakeSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "admin_notify_email", None)
    async with client() as c:
        sent = await c.post("/api/access-requests", json=form())
    assert sent.status_code == 204
    assert fake_sender.outbox == []


async def test_a_honeypot_hit_sends_nothing(notify: str, fake_sender: FakeSender) -> None:
    async with client() as c:
        await c.post("/api/access-requests", json=form(website="https://spam.example"))
    assert fake_sender.outbox == []


async def test_a_throttled_request_sends_nothing(notify: str, fake_sender: FakeSender) -> None:
    async with client("198.51.100.40") as c:
        for _ in range(3):
            await c.post("/api/access-requests", json=form())
        fourth = await c.post("/api/access-requests", json=form())
    assert fourth.status_code == 429
    assert len(fake_sender.outbox) == 3


async def test_a_sender_that_raises_never_fails_the_form(
    notify: str, fake_sender: FakeSender, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_sender.raises = RuntimeError("resend exploded")
    async with client() as c:
        sent = await c.post("/api/access-requests", json=form())
    assert sent.status_code == 204
    assert len(fake_sender.outbox) == 1
    assert "Ana Silva" in "\n".join(listed(capsys))


async def test_a_failed_send_never_fails_the_form(notify: str, fake_sender: FakeSender) -> None:
    fake_sender.result = SendResult("failed", error="Resend 422: nope")
    async with client() as c:
        sent = await c.post("/api/access-requests", json=form())
    assert sent.status_code == 204
