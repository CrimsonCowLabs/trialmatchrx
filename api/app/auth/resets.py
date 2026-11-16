"""Password-reset links (SPEC.md "Marketing and accounts": `make reset-link`, `/reset/[token]`).

`create` makes the token the CLI prints in a link; the table keeps only its SHA-256. A link
works once, for `RESET_TTL`, and never for a disabled account. That is checked when the link
is made and again when it is used. `redeem` sets the new password (same rules as everywhere,
`passwords.password_problem`), retires every outstanding link for that user and ends all of
their sessions.
"""

import datetime as dt
import secrets
from typing import Literal

from sqlmodel import Session, col, select, update

from app.auth import passwords, sessions
from app.auth.sessions import token_hash
from app.db import PasswordResetRow, UserRow, as_utc, session_scope, utcnow
from app.schemas import RESET_DISABLED, RESET_EXPIRED, RESET_UNKNOWN, RESET_USED

RESET_TTL = dt.timedelta(hours=1)
# Expired links are pruned only this long after they expire, so opening one late still says
# "expired" rather than "not valid".
KEEP_EXPIRED = dt.timedelta(days=7)


RefusalReason = Literal["unknown", "expired", "used", "disabled"]
MESSAGES: dict[RefusalReason, str] = {
    "unknown": RESET_UNKNOWN,
    "expired": RESET_EXPIRED,
    "used": RESET_USED,
    "disabled": RESET_DISABLED,
}


class ResetRefused(Exception):
    """The link can't be used: `reason` says why, `str(exc)` is the message for the person
    holding it."""

    def __init__(self, reason: RefusalReason) -> None:
        super().__init__(MESSAGES[reason])
        self.reason: RefusalReason = reason


class PasswordRejected(Exception):
    """The new password breaks the password rules; `str(exc)` says which."""


def create(user_id: str, *, now: dt.datetime | None = None) -> str:
    """A new reset link's token for `user_id` (never stored). Refuses a disabled account.
    Earlier links for the user keep working until they expire or one is used."""
    now = now or utcnow()
    token = secrets.token_urlsafe(32)  # 256 bits
    with session_scope() as s:
        user = s.get(UserRow, user_id)
        if user is None:
            raise LookupError(f"no user {user_id!r}")
        if user.disabled_at is not None:
            raise ResetRefused("disabled")
        old = s.exec(
            select(PasswordResetRow).where(col(PasswordResetRow.expires_at) <= now - KEEP_EXPIRED)
        ).all()
        for row in old:
            s.delete(row)
        s.add(
            PasswordResetRow(
                token_hash=token_hash(token),
                user_id=user_id,
                created_at=now,
                expires_at=now + RESET_TTL,
            )
        )
    return token


def _usable(s: Session, token: str, now: dt.datetime) -> UserRow:
    """The account `token`'s link resets, if the link can be used now; else ResetRefused."""
    row = s.get(PasswordResetRow, token_hash(token))
    user = s.get(UserRow, row.user_id) if row is not None else None
    if row is None or user is None:
        raise ResetRefused("unknown")
    if row.used_at is not None:
        raise ResetRefused("used")
    if as_utc(row.expires_at) <= now:
        raise ResetRefused("expired")
    if user.disabled_at is not None:
        raise ResetRefused("disabled")
    return user


def check(token: str, *, now: dt.datetime | None = None) -> UserRow:
    """The account a still-usable link resets, or ResetRefused. Changes nothing."""
    now = now or utcnow()
    with session_scope() as s:
        user = _usable(s, token, now)
        s.expunge(user)
        return user


def redeem(token: str, new_password: str, *, now: dt.datetime | None = None) -> UserRow:
    """Use the link: set `new_password`, retire every unused link for the user and end all of
    their sessions. ResetRefused if the link can't be used, PasswordRejected if the password
    breaks the rules (the link stays usable then)."""
    now = now or utcnow()
    # A dead link is reported before a weak password, and no Argon2 work is spent on it. The
    # write below checks the link again, in the transaction that claims it.
    check(token, now=now)
    problem = passwords.password_problem(new_password)
    if problem is not None:
        raise PasswordRejected(problem)
    hashed = passwords.hash_password(new_password)
    with session_scope() as s:
        user = _usable(s, token, now)
        # Claim the link with a conditional UPDATE: of two redemptions racing, one wins.
        claimed = s.exec(
            update(PasswordResetRow)
            .where(
                col(PasswordResetRow.token_hash) == token_hash(token),
                col(PasswordResetRow.used_at).is_(None),
            )
            .values(used_at=now)
        )
        if claimed.rowcount != 1:
            raise ResetRefused("used")
        s.exec(
            update(PasswordResetRow)
            .where(
                col(PasswordResetRow.user_id) == user.id,
                col(PasswordResetRow.used_at).is_(None),
            )
            .values(used_at=now)
        )
        user.password_hash = hashed
        # Same transaction: the new password and the end of the old sessions land together.
        sessions.end_user_sessions(s, user.id)
        s.flush()
        s.refresh(user)
        s.expunge(user)
    return user
