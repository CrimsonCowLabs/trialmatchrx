"""Request-access submissions (SPEC.md "Marketing and accounts", Request access): the form on
`/` writes one `access_requests` row per send. Spam handling is a honeypot field and a limit
of `MAX_PER_IP` stored requests per IP within a rolling `WINDOW`, no CAPTCHA.

The limit counts stored rows only, so a honeypot hit (never stored) doesn't use up an IP's
allowance, and a refused request doesn't extend the wait.
"""

import datetime as dt
import threading
from typing import Literal

from sqlalchemy import func
from sqlmodel import col, select

from app.db import AccessRequestRow, session_scope, utcnow
from app.schemas import AccessRequestCreate

MAX_PER_IP = 3
WINDOW = dt.timedelta(hours=1)

Outcome = Literal["stored", "honeypot", "throttled"]

# Count-then-insert runs as one step, or parallel sends from one IP could all pass the count.
# A process lock is enough: the API runs one worker (api/Dockerfile), as for sign-in.
_lock = threading.Lock()


def submit(body: AccessRequestCreate, ip: str, *, now: dt.datetime | None = None) -> Outcome:
    """Store the request, unless the honeypot is filled (a bot: nothing is stored) or `ip`
    already has `MAX_PER_IP` requests in the last `WINDOW`."""
    if body.website:
        return "honeypot"
    now = now or utcnow()
    with _lock, session_scope() as s:
        recent = s.exec(
            select(func.count()).where(
                col(AccessRequestRow.ip) == ip,
                col(AccessRequestRow.created_at) > now - WINDOW,
            )
        ).one()
        if recent >= MAX_PER_IP:
            return "throttled"
        s.add(
            AccessRequestRow(
                name=body.name,
                email=body.email,
                organization=body.organization,
                role=body.role,
                message=body.message or None,
                ip=ip,
                created_at=now,
            )
        )
    return "stored"
