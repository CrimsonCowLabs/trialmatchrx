"""The `sessions` table (SPEC.md "Marketing and accounts", Sessions).

The cookie holds an opaque random token; the table holds only its SHA-256. A session lasts
`SESSION_TTL` from its last use. Using it moves `last_used_at` forward, but at most once per
`TOUCH_EVERY`, so ordinary browsing isn't a database write on every request.
"""

import datetime as dt
import hashlib
import secrets
from typing import NamedTuple

from sqlmodel import col
from sqlmodel import delete as sql_delete

from app.db import SessionRow, UserRow, as_utc, session_scope, utcnow

SESSION_TTL = dt.timedelta(days=30)
TOUCH_EVERY = dt.timedelta(minutes=1)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(user_id: str, *, now: dt.datetime | None = None) -> str:
    """Start a session for `user_id`; returns the token for the cookie (never stored).
    Also deletes every expired session, so abandoned ones don't pile up."""
    now = now or utcnow()
    token = secrets.token_urlsafe(32)  # 256 bits
    with session_scope() as s:
        s.exec(sql_delete(SessionRow).where(col(SessionRow.last_used_at) <= now - SESSION_TTL))
        s.add(
            SessionRow(
                token_hash=token_hash(token), user_id=user_id, created_at=now, last_used_at=now
            )
        )
    return token


class Resolved(NamedTuple):
    user: UserRow
    # True when this use moved the expiry forward, so the cookie's Max-Age should be re-sent.
    rolled: bool


def resolve(token: str, *, now: dt.datetime | None = None) -> Resolved | None:
    """The live session's user, or None: unknown token, expired (the row is deleted), or a
    disabled user. Rolls the expiry forward when the last touch is over a minute old."""
    if not token:
        return None
    now = now or utcnow()
    with session_scope() as s:
        row = s.get(SessionRow, token_hash(token))
        if row is None:
            return None
        idle = now - as_utc(row.last_used_at)
        if idle >= SESSION_TTL:
            s.delete(row)
            return None
        user = s.get(UserRow, row.user_id)
        if user is None or user.disabled_at is not None:
            return None
        rolled = idle >= TOUCH_EVERY
        if rolled:
            row.last_used_at = now
        s.expunge(user)
        return Resolved(user, rolled)


def end_user_sessions(user_id: str) -> int:
    """End every session `user_id` has, in every browser; returns how many."""
    with session_scope() as s:
        result = s.exec(sql_delete(SessionRow).where(col(SessionRow.user_id) == user_id))
        return int(result.rowcount)


def delete(token: str) -> None:
    """End the session (sign-out). Unknown tokens are ignored."""
    with session_scope() as s:
        row = s.get(SessionRow, token_hash(token))
        if row is not None:
            s.delete(row)
