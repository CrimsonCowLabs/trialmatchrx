"""Sign-in throttle (SPEC.md "Marketing and accounts", Login): after `MAX_FAILURES` failed
sign-ins within `WINDOW` for the same email OR the same IP, further attempts are refused
without checking the password. It's a rolling window over the `login_failures` table, so it
lifts on its own; accounts never lock. Throttled attempts aren't recorded as failures, so
hammering a throttled email doesn't extend the wait.

A wrong current password when changing your password has its own limit, per account, in
`password_change_failures`: the same numbers, but it neither counts toward sign-in's nor is
blocked by it, so someone holding a stolen session can't lock the owner out of signing in.
"""

import datetime as dt

from sqlalchemy import func
from sqlmodel import col, delete, select

from app.auth.users import normalize_email
from app.db import LoginFailureRow, PasswordChangeFailureRow, session_scope, utcnow

MAX_FAILURES = 5
WINDOW = dt.timedelta(minutes=15)


def record_failure(email: str, ip: str, *, now: dt.datetime | None = None) -> None:
    """Log one failed sign-in, and prune failures that fell out of the window."""
    now = now or utcnow()
    with session_scope() as s:
        s.exec(delete(LoginFailureRow).where(col(LoginFailureRow.failed_at) <= now - WINDOW))
        s.add(LoginFailureRow(email=normalize_email(email), ip=ip, failed_at=now))


def is_throttled(email: str, ip: str, *, now: dt.datetime | None = None) -> bool:
    """Whether the email or the IP has `MAX_FAILURES` failures in the last `WINDOW`. An empty
    email (a passkey sign-in that names no known account) checks the IP only: those failures
    are stored with email "", and one shared bucket would let anyone throttle everyone."""
    now = now or utcnow()
    recent = col(LoginFailureRow.failed_at) > now - WINDOW
    matches = [col(LoginFailureRow.ip) == ip]
    if normalized := normalize_email(email):
        matches.append(col(LoginFailureRow.email) == normalized)
    with session_scope() as s:
        for match in matches:
            count = s.exec(select(func.count()).where(recent, match)).one()
            if count >= MAX_FAILURES:
                return True
    return False


def record_password_change_failure(user_id: str, *, now: dt.datetime | None = None) -> None:
    """Log one wrong current password for `user_id`, and prune what fell out of the window."""
    now = now or utcnow()
    with session_scope() as s:
        s.exec(
            delete(PasswordChangeFailureRow).where(
                col(PasswordChangeFailureRow.failed_at) <= now - WINDOW
            )
        )
        s.add(PasswordChangeFailureRow(user_id=user_id, failed_at=now))


def password_change_throttled(user_id: str, *, now: dt.datetime | None = None) -> bool:
    """Whether `user_id` has `MAX_FAILURES` wrong current passwords in the last `WINDOW`."""
    now = now or utcnow()
    with session_scope() as s:
        count = s.exec(
            select(func.count()).where(
                col(PasswordChangeFailureRow.user_id) == user_id,
                col(PasswordChangeFailureRow.failed_at) > now - WINDOW,
            )
        ).one()
    return count >= MAX_FAILURES
