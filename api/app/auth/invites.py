"""The `invites` table (SPEC.md "Marketing and accounts", Accounts): accounts start from a
one-time link that expires after 7 days.

The link carries an opaque random token; the table holds only its SHA-256, like a session.
`create` refuses an email that already has an account. `accept` creates the account and spends
the invite in one transaction, so a link can't be used twice even by two requests at once, and
a refused link creates nothing.
"""

import datetime as dt
import secrets
import uuid
from typing import Literal, NamedTuple

from sqlalchemy import update
from sqlmodel import Session, col, select

from app.auth.sessions import token_hash
from app.auth.users import find_by_email, normalize_email
from app.db import InviteRow, UserRow, as_utc, session_scope, utcnow

INVITE_TTL = dt.timedelta(days=7)

Unusable = Literal["unknown", "expired", "used"]


class AlreadyHasAccount(Exception):
    """The invited email already has an account."""


class InviteUnusable(Exception):
    def __init__(self, reason: Unusable) -> None:
        super().__init__(reason)
        self.reason: Unusable = reason


class Issued(NamedTuple):
    token: str  # goes in the link; never stored
    expires_at: dt.datetime


def create(email: str, *, now: dt.datetime | None = None) -> Issued:
    """A new invite for `email`. Raises AlreadyHasAccount if the email has an account.
    Earlier unused invites for the same email keep working until one of them is accepted."""
    now = now or utcnow()
    if find_by_email(email) is not None:
        raise AlreadyHasAccount(normalize_email(email))
    token = secrets.token_urlsafe(32)  # 256 bits
    expires_at = now + INVITE_TTL
    with session_scope() as s:
        s.add(
            InviteRow(
                token_hash=token_hash(token),
                email=normalize_email(email),
                created_at=now,
                expires_at=expires_at,
            )
        )
    return Issued(token, expires_at)


def _usable(s: Session, token: str, now: dt.datetime) -> InviteRow:
    row = s.get(InviteRow, token_hash(token)) if token else None
    if row is None:
        raise InviteUnusable("unknown")
    if row.used_at is not None:
        raise InviteUnusable("used")
    if now >= as_utc(row.expires_at):
        raise InviteUnusable("expired")
    if s.exec(select(UserRow).where(UserRow.email == row.email)).first() is not None:
        raise AlreadyHasAccount(row.email)  # the email got an account after the invite
    return row


def lookup(token: str, *, now: dt.datetime | None = None) -> InviteRow:
    """The usable invite for `token`. Raises InviteUnusable (unknown, used or expired) or
    AlreadyHasAccount (the email got an account after the invite was made)."""
    with session_scope() as s:
        row = _usable(s, token, now or utcnow())
        s.expunge(row)
    return row


def accept(token: str, *, password_hash: str | None, now: dt.datetime | None = None) -> UserRow:
    """Spend the invite and create its account (`password_hash` None would be passkey-only,
    for #4). Raises like `lookup`; on any refusal nothing is created and the invite is
    unchanged."""
    now = now or utcnow()
    with session_scope() as s:
        row = _usable(s, token, now)
        # Conditional, so of two requests racing on one link only one spends it.
        spent = s.connection().execute(
            update(InviteRow)
            .where(col(InviteRow.token_hash) == row.token_hash)
            .where(col(InviteRow.used_at).is_(None))
            .values(used_at=now)
        )
        if spent.rowcount != 1:
            raise InviteUnusable("used")
        user = UserRow(
            id=uuid.uuid4().hex, email=row.email, password_hash=password_hash, created_at=now
        )
        s.add(user)
        s.flush()
        s.refresh(user)
        s.expunge(user)
    return user
