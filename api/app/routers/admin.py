"""`/api/admin/*`: the admin page (SPEC.md "Admin"). Every route is behind `require_admin`, set on
the router, so a signed-out caller, a non-admin and a disabled admin all get 404 `Not Found`. The
app-wide session gate skips this prefix (`deps.is_admin_path`) so it can't answer 401 first.

Grant access creates the invite without touching the request, sends the email, and only then
marks the email's pending requests `invited`: a failed send leaves the invite in place (the
admin copies the link) and the request `pending` (SPEC.md "Admin", Sending). Granting a request
that's already `invited` is Resend invite: a new link, and the old one stops working.

Admin housekeeping, not an agent run: like sign-in, its decisions go to a logger rather than
a TraceRecorder (see `app/routers/auth.py`).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, select

from app import access_requests
from app.auth import invites
from app.auth.deps import require_admin
from app.auth.users import normalize_email
from app.config import get_settings
from app.db import AccessRequestRow, InviteRow, UserRow, as_utc, session_scope, utcnow
from app.emails import render
from app.emails.sender import Sender, SendResult, get_sender
from app.schemas import (
    GRANT_ACCOUNT_EXISTS,
    REQUEST_DISMISSED,
    REQUEST_NOT_FOUND,
    REQUEST_NOT_PENDING,
    AccessRequestAdmin,
    AccessRequestState,
    AdminUser,
    GrantAccessRequest,
    GrantResult,
)

log = logging.getLogger("app.admin")

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    responses={404: {"description": "Not Found: not a signed-in admin, or no such request"}},
)

Admin = Annotated[UserRow, Depends(require_admin)]  # cached: require_admin runs once a request


def _state(row: AccessRequestRow, user: UserRow | None, invite_open: bool) -> AccessRequestState:
    if user is not None:
        return "joined"
    if row.status == "invited":
        return "invited" if invite_open else "invite_expired"
    return "dismissed" if row.status == "dismissed" else "pending"


@router.get("/access-requests", response_model=list[AccessRequestAdmin])
def list_access_requests() -> list[AccessRequestAdmin]:
    """Every request, pending first, then newest first, with what the page shows for it."""
    rows = access_requests.list_requests()
    emails = {normalize_email(r.email) for r in rows}
    now = utcnow()
    with session_scope() as s:  # two queries for the whole list, not two per row
        accounts = {
            u.email: u for u in s.exec(select(UserRow).where(col(UserRow.email).in_(emails)))
        }
        latest: dict[str, InviteRow] = {}
        for invite in s.exec(
            select(InviteRow)
            .where(col(InviteRow.email).in_(emails))
            .order_by(col(InviteRow.created_at))
        ):
            latest[invite.email] = invite  # ascending, so the newest wins
        s.expunge_all()
    out = []
    for r in rows:
        email = normalize_email(r.email)
        user = accounts.get(email)
        inv = latest.get(email)
        invite_open = inv is not None and inv.used_at is None and as_utc(inv.expires_at) > now
        assert r.id is not None
        out.append(
            AccessRequestAdmin(
                id=r.id,
                name=r.name,
                email=r.email,
                organization=r.organization,
                role=r.role,  # validated: stored from AccessRole
                message=r.message,
                created_at=as_utc(r.created_at),
                status=r.status,  # validated: stored from AccessRequestStatus
                handled_at=as_utc(r.handled_at) if r.handled_at else None,
                state=_state(r, user, invite_open),
                has_account=user is not None,
                has_open_invite=invite_open,
                joined_at=as_utc(user.created_at) if user else None,
                invite_expires_at=as_utc(inv.expires_at) if inv else None,
            )
        )
    return out


def _get_request(request_id: int) -> AccessRequestRow:
    with session_scope() as s:
        row = s.get(AccessRequestRow, request_id)
        if row is None:
            raise HTTPException(status_code=404, detail=REQUEST_NOT_FOUND)
        s.expunge(row)
    return row


def _send(sender: Sender, to: str, subject: str, text: str, html: str) -> SendResult:
    """The sender's result; a sender that raises counts as a failed send."""
    try:
        return sender.send(to, subject, text, html)
    except Exception as e:
        log.exception("invite email to %s failed", to)
        return SendResult("failed", error=f"Couldn't send: {e}")


@router.post(
    "/access-requests/{request_id}/grant",
    response_model=GrantResult,
    responses={409: {"description": f"{GRANT_ACCOUNT_EXISTS} / {REQUEST_DISMISSED}"}},
)
def grant_access_request(
    request_id: int,
    body: GrantAccessRequest,
    admin: Admin,
    sender: Annotated[Sender, Depends(get_sender)],
) -> GrantResult:
    """Invite the request's email (7 days) and email the link, with the note on top. Also Resend
    invite, on a request already `invited`. 409 if the email has an account or the request was
    dismissed. See GrantResult for what each email_status means."""
    row = _get_request(request_id)
    if row.status == "dismissed":
        raise HTTPException(status_code=409, detail=REQUEST_DISMISSED)
    now = utcnow()
    try:
        issued = invites.create(row.email, handled_by=admin.id, now=now, mark_requests=False)
    except invites.AlreadyHasAccount as err:
        raise HTTPException(status_code=409, detail=GRANT_ACCOUNT_EXISTS) from err
    link = f"{get_settings().app_url.rstrip('/')}/invite/{issued.token}"
    expires_days = str(invites.INVITE_TTL.days)
    subject, text, html = render(
        "invite", note=(body.note or "").strip(), link=link, expires_days=expires_days
    )
    to = normalize_email(row.email)
    result = _send(sender, to, subject, text, html)
    log.info("access request %s granted by %s: email %s", request_id, admin.id, result.status)
    if result.status == "failed":
        return GrantResult(email_status="failed", error=result.error, link=link)
    invites.mark_requests_invited(to, handled_by=admin.id, now=now)
    return GrantResult(email_status=result.status, link=link if result.status == "logged" else None)


@router.post(
    "/access-requests/{request_id}/dismiss",
    status_code=204,
    responses={409: {"description": REQUEST_NOT_PENDING}},
)
def dismiss_access_request(request_id: int, admin: Admin) -> None:
    """Mark a pending request `dismissed`. No email is sent. 409 if it isn't pending."""
    if access_requests.dismiss(request_id, admin.id):
        log.info("access request %s dismissed by %s", request_id, admin.id)
        return
    _get_request(request_id)  # 404 if unknown
    raise HTTPException(status_code=409, detail=REQUEST_NOT_PENDING)


@router.get("/users", response_model=list[AdminUser])
def list_users() -> list[AdminUser]:
    """Every account, newest first (read-only; disabling stays on the CLI)."""
    with session_scope() as s:
        rows = list(
            s.exec(select(UserRow).order_by(col(UserRow.created_at).desc(), col(UserRow.id)))
        )
        return [
            AdminUser(
                id=u.id,
                email=u.email,
                is_admin=u.is_admin,
                created_at=as_utc(u.created_at),
                last_login_at=as_utc(u.last_login_at) if u.last_login_at else None,
                disabled_at=as_utc(u.disabled_at) if u.disabled_at else None,
            )
            for u in rows
        ]
