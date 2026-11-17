"""SPEC.md "Admin": `/api/admin/*`, the API behind `/app/admin`. Only a signed-in admin gets in;
anyone else gets 404. Requests come back pending first with what the page shows for each; Grant
access makes the invite and emails it (a failed send leaves the request pending and hands the
admin the link); Dismiss marks a pending one; Users is read-only."""

import datetime as dt
import re
from typing import Any

import httpx
import pytest
from fastapi.routing import iter_route_contexts
from sqlmodel import select

from app.auth import invites, sessions, users
from app.auth.deps import SESSION_COOKIE
from app.config import get_settings
from app.db import AccessRequestRow, InviteRow, UserRow, session_scope, utcnow
from app.emails.sender import SendResult
from app.main import app
from tests.email_fake import FakeSender

DAY = dt.timedelta(days=1)


def make_account(email: str, *, admin: bool = False, at: dt.datetime | None = None) -> UserRow:
    with session_scope() as s:
        row = UserRow(id=email.split("@")[0], email=email, is_admin=admin)
        if at is not None:
            row.created_at = at
        s.add(row)
        s.flush()
        s.refresh(row)
        s.expunge(row)
    return row


def admin_client(*, admin: bool = True, csrf: bool = True) -> httpx.AsyncClient:
    """Signed in as boss@example.com (an admin unless `admin=False`; made on first use)."""
    user = users.find_by_email("boss@example.com") or make_account("boss@example.com", admin=admin)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"} if csrf else None,
        cookies={SESSION_COOKIE: sessions.create(user.id)},
    )


def add_request(
    email: str = "ana@acme.example",
    *,
    at: dt.datetime | None = None,
    status: str = "pending",
    name: str = "Ana Silva",
) -> int:
    with session_scope() as s:
        row = AccessRequestRow(
            name=name,
            email=email,
            organization="Acme",
            role="sponsor",
            message="We run ALS trials.",
            ip="203.0.113.9",
            created_at=at or utcnow(),
            status=status,
        )
        s.add(row)
        s.flush()
        assert row.id is not None
        return row.id


def stored(request_id: int) -> AccessRequestRow:
    with session_scope() as s:
        row = s.get(AccessRequestRow, request_id)
        assert row is not None
        s.expunge(row)
    return row


def invites_for(email: str) -> list[InviteRow]:
    with session_scope() as s:
        rows = list(s.exec(select(InviteRow).where(InviteRow.email == email)))
        s.expunge_all()
    return rows


def admin_endpoints() -> list[tuple[str, str]]:
    return [
        (method, re.sub(r"\{[^}]+\}", "1", r.path or ""))
        for r in iter_route_contexts(app.routes)
        if (r.path or "").startswith("/api/admin/")
        for method in sorted(r.methods or ())
    ]


def test_the_admin_routes_are_the_four() -> None:
    assert sorted(admin_endpoints()) == [
        ("GET", "/api/admin/access-requests"),
        ("GET", "/api/admin/users"),
        ("POST", "/api/admin/access-requests/1/dismiss"),
        ("POST", "/api/admin/access-requests/1/grant"),
    ]


@pytest.mark.parametrize(("method", "path"), admin_endpoints())
async def test_a_signed_in_non_admin_gets_404(method: str, path: str) -> None:
    add_request()
    async with admin_client(admin=False) as c:
        res = await c.request(method, path, json={})
    assert (res.status_code, res.json()) == (404, {"detail": "Not Found"})
    assert stored(1).status == "pending"


@pytest.mark.parametrize(("method", "path"), admin_endpoints())
async def test_signed_out_gets_404(method: str, path: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    ) as c:
        res = await c.request(method, path, json={})
    assert (res.status_code, res.json()) == (404, {"detail": "Not Found"})


async def test_posts_need_the_csrf_header() -> None:
    rid = add_request()
    async with admin_client(csrf=False) as c:
        for action in ("grant", "dismiss"):
            res = await c.post(f"/api/admin/access-requests/{rid}/{action}", json={})
            assert res.status_code == 403
        assert (await c.get("/api/admin/users")).status_code == 200  # a GET needs none
    assert stored(rid).status == "pending"


async def test_requests_are_pending_first_then_newest_with_every_state() -> None:
    now = utcnow()
    old_pending = add_request("old@acme.example", at=now - 5 * DAY)
    new_pending = add_request("new@acme.example", at=now - DAY)
    dismissed = add_request("gone@acme.example", at=now - 2 * DAY, status="dismissed")
    # invited, with an open invite
    open_id = add_request("open@acme.example", at=now - 3 * DAY)
    open_invite = invites.create("open@acme.example")
    # invited, but the invite ran out
    expired_id = add_request("late@acme.example", at=now - 4 * DAY)
    invites.create("late@acme.example", now=now - 8 * DAY)
    # invited, then joined (email typed with capitals: matched normalized)
    joined_id = add_request("Joe@Acme.example", at=now - 6 * DAY)
    invites.create("joe@acme.example")
    joe = make_account("joe@acme.example", at=now - DAY)
    # still pending, but the email has an account: joined whatever the status
    pending_joined = add_request("pat@acme.example", at=now - 7 * DAY)
    make_account("pat@acme.example")

    async with admin_client() as c:
        res = await c.get("/api/admin/access-requests")
    assert res.status_code == 200
    rows = {r["id"]: r for r in res.json()}
    order = [r["id"] for r in res.json()]
    assert order == [
        new_pending,
        old_pending,
        pending_joined,
        dismissed,
        open_id,
        expired_id,
        joined_id,
    ]
    assert {i: r["state"] for i, r in rows.items()} == {
        new_pending: "pending",
        old_pending: "pending",
        pending_joined: "joined",
        dismissed: "dismissed",
        open_id: "invited",
        expired_id: "invite_expired",
        joined_id: "joined",
    }
    first = rows[new_pending]
    assert first == {
        "id": new_pending,
        "name": "Ana Silva",
        "email": "new@acme.example",
        "organization": "Acme",
        "role": "sponsor",
        "message": "We run ALS trials.",
        "created_at": first["created_at"],
        "status": "pending",
        "handled_at": None,
        "state": "pending",
        "has_account": False,
        "has_open_invite": False,
        "joined_at": None,
        "invite_expires_at": None,
    }
    assert rows[open_id]["has_open_invite"] is True
    assert rows[open_id]["invite_expires_at"] == open_invite.expires_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert rows[open_id]["handled_at"] is not None
    assert rows[expired_id]["has_open_invite"] is False
    assert rows[expired_id]["invite_expires_at"] is not None
    assert rows[joined_id]["status"] == "invited"
    assert rows[joined_id]["has_account"] is True
    assert rows[joined_id]["joined_at"].startswith(joe.created_at.isoformat()[:19])
    assert rows[pending_joined]["status"] == "pending"
    assert rows[pending_joined]["has_account"] is True


def _link_in(text: str) -> str:
    match = re.search(r"https?://\S+/invite/\S+", text)
    assert match is not None, text
    return match.group(0)


async def grant(rid: int, **body: Any) -> httpx.Response:
    async with admin_client() as c:
        return await c.post(f"/api/admin/access-requests/{rid}/grant", json=body)


async def test_grant_emails_the_invite_and_marks_the_request(fake_sender: FakeSender) -> None:
    rid = add_request("Ana@Acme.example")
    res = await grant(rid, note="Hi Ana,\nGood to hear from you.")
    assert res.status_code == 200
    assert res.json() == {"email_status": "sent", "error": None, "link": None}
    [email] = fake_sender.outbox
    assert email.to == "ana@acme.example"
    assert email.text.startswith("Hi Ana,\nGood to hear from you.")
    link = _link_in(email.text)
    assert link.startswith(f"{get_settings().app_url.rstrip('/')}/invite/")
    token = link.rsplit("/", 1)[1]
    assert invites.lookup(token).email == "ana@acme.example"
    row = stored(rid)
    assert row.status == "invited"
    assert row.handled_by == "boss" and row.handled_at is not None


async def test_grant_without_a_key_is_logged_and_returns_the_link(
    fake_sender: FakeSender,
) -> None:
    fake_sender.result = SendResult("logged")
    rid = add_request()
    res = await grant(rid, note=None)
    body = res.json()
    assert (res.status_code, body["email_status"], body["error"]) == (200, "logged", None)
    assert body["link"] == _link_in(fake_sender.outbox[0].text)
    assert stored(rid).status == "invited"


@pytest.mark.parametrize("how", ["failed", "raises"])
async def test_a_failed_send_keeps_the_invite_and_the_request_pending(
    fake_sender: FakeSender, how: str
) -> None:
    if how == "failed":
        fake_sender.result = SendResult("failed", error="Resend 422: bad from")
    else:
        fake_sender.raises = RuntimeError("boom")
    rid = add_request()
    other = add_request(name="Ana again")  # a repeat request from the same email
    res = await grant(rid)
    body = res.json()
    assert (res.status_code, body["email_status"]) == (200, "failed")
    assert body["error"] == ("Resend 422: bad from" if how == "failed" else "Couldn't send: boom")
    token = body["link"].rsplit("/", 1)[1]
    assert invites.lookup(token).email == "ana@acme.example"  # the link works
    assert stored(rid).status == "pending" and stored(rid).handled_at is None
    assert stored(other).status == "pending"
    async with admin_client() as c:
        [row, _] = (await c.get("/api/admin/access-requests")).json()
    assert (row["state"], row["has_open_invite"]) == ("pending", True)


async def test_grant_refuses_an_email_with_an_account(fake_sender: FakeSender) -> None:
    rid = add_request("joe@acme.example")
    make_account("joe@acme.example")
    res = await grant(rid)
    assert (res.status_code, res.json()) == (409, {"detail": "This email already has an account."})
    assert fake_sender.outbox == []
    assert invites_for("joe@acme.example") == []


async def test_grant_refuses_a_dismissed_request(fake_sender: FakeSender) -> None:
    rid = add_request(status="dismissed")
    res = await grant(rid)
    assert (res.status_code, res.json()) == (409, {"detail": "This request was dismissed."})
    assert fake_sender.outbox == []


async def test_grant_an_unknown_request_is_404() -> None:
    res = await grant(999)
    assert (res.status_code, res.json()) == (404, {"detail": "No such access request."})


async def test_grant_caps_the_note() -> None:
    rid = add_request()
    assert (await grant(rid, note="x" * 2001)).status_code == 422
    assert stored(rid).status == "pending"


async def test_resend_after_expiry_makes_a_new_link(fake_sender: FakeSender) -> None:
    rid = add_request()
    old = invites.create("ana@acme.example", now=utcnow() - 8 * DAY)
    res = await grant(rid)
    assert res.json()["email_status"] == "sent"
    new_token = _link_in(fake_sender.outbox[0].text).rsplit("/", 1)[1]
    assert invites.lookup(new_token).email == "ana@acme.example"
    with pytest.raises(invites.InviteUnusable):
        invites.lookup(old.token)
    async with admin_client() as c:
        [row] = (await c.get("/api/admin/access-requests")).json()
    assert row["state"] == "invited"


async def test_resend_an_open_invite_cancels_the_old_link(fake_sender: FakeSender) -> None:
    rid = add_request()
    first = (await grant(rid)).status_code
    old_token = _link_in(fake_sender.outbox[0].text).rsplit("/", 1)[1]
    assert (first, (await grant(rid)).status_code) == (200, 200)
    with pytest.raises(invites.InviteUnusable):
        invites.lookup(old_token)
    assert invites.lookup(_link_in(fake_sender.outbox[1].text).rsplit("/", 1)[1])


async def test_dismiss() -> None:
    rid = add_request()
    async with admin_client() as c:
        res = await c.post(f"/api/admin/access-requests/{rid}/dismiss")
        assert (res.status_code, res.content) == (204, b"")
        row = stored(rid)
        assert (row.status, row.handled_by) == ("dismissed", "boss")
        again = await c.post(f"/api/admin/access-requests/{rid}/dismiss")
        assert (again.status_code, again.json()) == (
            409,
            {"detail": "This request has already been handled."},
        )
        unknown = await c.post("/api/admin/access-requests/999/dismiss")
        assert (unknown.status_code, unknown.json()) == (404, {"detail": "No such access request."})


async def test_dismiss_an_invited_request_is_409() -> None:
    rid = add_request(status="invited")
    async with admin_client() as c:
        res = await c.post(f"/api/admin/access-requests/{rid}/dismiss")
    assert res.status_code == 409
    assert stored(rid).status == "invited"


async def test_users_newest_first() -> None:
    now = utcnow()
    make_account("old@example.com", at=now - 3 * DAY)
    with session_scope() as s:
        s.add(
            UserRow(
                id="gone",
                email="gone@example.com",
                created_at=now - 2 * DAY,
                last_login_at=now - DAY,
                disabled_at=now,
            )
        )
    async with admin_client() as c:  # boss@example.com, created now
        res = await c.get("/api/admin/users")
    assert res.status_code == 200
    listed = res.json()
    emails = [u["email"] for u in listed]
    assert emails == ["boss@example.com", "gone@example.com", "old@example.com"]
    assert listed[0]["is_admin"] is True and listed[0]["last_login_at"] is None
    gone = listed[1]
    assert set(gone) == {"id", "email", "is_admin", "created_at", "last_login_at", "disabled_at"}
    assert gone["is_admin"] is False
    assert gone["last_login_at"] is not None and gone["disabled_at"] is not None
