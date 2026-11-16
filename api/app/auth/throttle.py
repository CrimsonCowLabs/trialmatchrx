"""Sign-in throttle (SPEC.md "Marketing and accounts", Login): after `MAX_FAILURES` failed
sign-ins within `WINDOW` for the same email OR the same IP, further attempts are refused
without checking the password. It's a rolling window over the `login_failures` table, so it
lifts on its own; accounts never lock. Throttled attempts aren't recorded as failures, so
hammering a throttled email doesn't extend the wait.
"""

import datetime as dt

from sqlalchemy import func
from sqlmodel import col, delete, select

from app.auth.users import normalize_email
from app.db import LoginFailureRow, session_scope, utcnow

MAX_FAILURES = 5
WINDOW = dt.timedelta(minutes=15)


def record_failure(email: str, ip: str, *, now: dt.datetime | None = None) -> None:
    """Log one failed sign-in, and prune failures that fell out of the window."""
    now = now or utcnow()
    with session_scope() as s:
        s.exec(delete(LoginFailureRow).where(col(LoginFailureRow.failed_at) <= now - WINDOW))
        s.add(LoginFailureRow(email=normalize_email(email), ip=ip, failed_at=now))


def is_throttled(email: str, ip: str, *, now: dt.datetime | None = None) -> bool:
    """Whether the email or the IP has `MAX_FAILURES` failures in the last `WINDOW`."""
    now = now or utcnow()
    recent = col(LoginFailureRow.failed_at) > now - WINDOW
    with session_scope() as s:
        for match in (
            col(LoginFailureRow.email) == normalize_email(email),
            col(LoginFailureRow.ip) == ip,
        ):
            count = s.exec(select(func.count()).where(recent, match)).one()
            if count >= MAX_FAILURES:
                return True
    return False
