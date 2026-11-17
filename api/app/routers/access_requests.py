"""`POST /api/access-requests`: the request-access form on `/` (SPEC.md "Marketing and
accounts"). Public, no session (SPEC.md Enforcement lists it among the exemptions). It's a
POST, so the CSRF guard still wants `X-Requested-With`, which the web client always sends.

A stored request is emailed to `ADMIN_NOTIFY_EMAIL` (SPEC.md "Admin", New-request email)
after the response, so a failed send never blocks or fails the form. A honeypot hit or a
throttled request sends nothing.

Not an agent run, so like sign-in its decisions go to a logger rather than a TraceRecorder
(see `app/routers/auth.py`).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app import access_requests
from app.auth.client_ip import request_ip
from app.config import get_settings
from app.emails import render
from app.emails.sender import Sender, get_sender
from app.schemas import ACCESS_REQUESTS_THROTTLED, AccessRequestCreate

log = logging.getLogger("app.access_requests")

router = APIRouter(prefix="/api/access-requests", tags=["access-requests"])


def notify_admin(sender: Sender, to: str, body: AccessRequestCreate) -> None:
    """Email one stored request to `to`, Reply-To the requester. Runs after the response;
    every failure is logged, none raised."""
    try:
        subject, text, html = render(
            "new_request",
            name=body.name,
            email=body.email,
            organization=body.organization,
            role=body.role,
            message=body.message or "",
            admin_url=f"{get_settings().app_url.rstrip('/')}/app/admin",
        )
        result = sender.send(to, subject, text, html, reply_to=body.email)
    except Exception:
        log.exception("new-request email to %s failed", to)
        return
    if result.status == "failed":
        log.warning("new-request email to %s failed: %s", to, result.error)


@router.post(
    "",
    status_code=204,
    responses={
        422: {"description": "A field is missing, too long, or not valid"},
        429: {"description": ACCESS_REQUESTS_THROTTLED},
    },
)
def create_access_request(
    body: AccessRequestCreate,
    request: Request,
    background: BackgroundTasks,
    sender: Annotated[Sender, Depends(get_sender)],
) -> None:
    """Send a request for access. A filled honeypot gets the same 204 and stores nothing; a
    4th stored request within an hour from one IP is a 429."""
    ip = request_ip(request)
    outcome = access_requests.submit(body, ip)
    log.info("access request %s ip=%s", outcome, ip)
    if outcome == "throttled":
        raise HTTPException(status_code=429, detail=ACCESS_REQUESTS_THROTTLED)
    notify_to = get_settings().admin_notify_email
    if outcome == "stored" and notify_to:
        background.add_task(notify_admin, sender, notify_to, body)
