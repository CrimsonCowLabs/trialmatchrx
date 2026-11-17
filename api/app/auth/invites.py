"""The `invites` table (SPEC.md "Marketing and accounts", Accounts): accounts start from a
one-time link that expires after 7 days.

The link carries an opaque random token; the table holds only its SHA-256, like a session.
`create` refuses an email that already has an account, cancels that email's older unused
invites and marks its pending access requests `invited` (SPEC.md "Admin"). `accept` creates
the account and spends the invite in one transaction, so a link can't be used twice even by
two requests at once, and a refused link creates nothing.
"""

import datetime as dt
import secrets
import uuid
from typing import Literal, NamedTuple

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.auth.sessions import token_hash
from app.auth.users import find_by_email, normalize_email
from app.db import (
    AccessRequestRow,
    InviteRow,
    PasskeyRow,
    UserRow,
    as_utc,
    session_scope,
    utcnow,
)

INVITE_TTL = dt.timedelta(days=7)

Unusable = Literal["unknown", "expired", "used"]


class InviteRefused(Exception):
    """Why an invite can't be made or used; nothing was created."""


class AlreadyHasAccount(InviteRefused):
    """The invited email already has an account."""


class InviteUnusable(InviteRefused):
    def __init__(self, reason: Unusable) -> None:
        super().__init__(reason)
        self.reason: Unusable = reason


class Issued(NamedTuple):
    token: str  # goes in the link; never stored
    expires_at: dt.datetime


def create(email: str, *, handled_by: str | None = None, now: dt.datetime | None = None) -> Issued:
    """A new invite for `email`. Raises AlreadyHasAccount if the email has an account.
    Earlier unused invites for the same email are cancelled: they expire now, so only the
    newest link works and an old one reads as expired. In the same transaction, the email's
    `pending` access requests become `invited` (SPEC.md "Admin", Request status), stamped `now`
    and `handled_by` (the granting admin's user id; None from the CLI)."""
    now = now or utcnow()
    email = normalize_email(email)
    if find_by_email(email) is not None:
        raise AlreadyHasAccount(email)
    token = secrets.token_urlsafe(32)  # 256 bits
    expires_at = now + INVITE_TTL
    with session_scope() as s:
        _mark_requests_invited(s, email, handled_by=handled_by, now=now)
        s.connection().execute(
            update(InviteRow)
            .where(col(InviteRow.email) == email)
            .where(col(InviteRow.used_at).is_(None))
            .where(col(InviteRow.expires_at) > now)
            .values(expires_at=now)
        )
        s.add(
            InviteRow(
                token_hash=token_hash(token),
                email=email,
                created_at=now,
                expires_at=expires_at,
            )
        )
    return Issued(token, expires_at)


def _mark_requests_invited(
    s: Session, email: str, *, handled_by: str | None, now: dt.datetime
) -> None:
    """`pending` -> `invited` for each request from `email` (already normalized). Request
    emails are stored as typed, so they're compared normalized here, in Python: SQLite's
    lower() only folds ASCII. Pending rows are few."""
    pending = s.exec(select(AccessRequestRow).where(AccessRequestRow.status == "pending"))
    for row in pending:
        if normalize_email(row.email) == email:
            row.status = "invited"
            row.handled_at = now
            row.handled_by = handled_by
            s.add(row)


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


class PasskeyTaken(Exception):
    """The passkey to add is already on an account (not a problem with the invite itself)."""


def accept(
    token: str,
    *,
    password_hash: str | None,
    passkey: PasskeyRow | None = None,
    now: dt.datetime | None = None,
) -> UserRow:
    """Spend the invite and create its account with this password and/or passkey (a verified,
    unsaved row from `passkeys.verify_registration`, whose `user_id` is the new account's id).
    Raises like `lookup`, ValueError with neither (an account must be able to sign in), or
    PasskeyTaken; on any refusal nothing is created and the invite is unchanged.

    If this refuses after the passkey was made, the person's device keeps a passkey for an
    account that never existed; signing in with it fails like any unknown passkey."""
    if password_hash is None and passkey is None:
        raise ValueError("an account needs a password or a passkey")
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
        email = row.email  # read now: after a failed flush the row can't be loaded
        user = UserRow(
            id=passkey.user_id if passkey is not None else uuid.uuid4().hex,
            email=email,
            password_hash=password_hash,
            created_at=now,
        )
        s.add(user)
        try:
            s.flush()
        except IntegrityError as err:
            # An account for this email landed at the same moment (an older invite accepted
            # while this one was made): users.email is unique, so this one loses and rolls
            # back (its invite stays unspent).
            raise AlreadyHasAccount(email) from err
        if passkey is not None:
            s.add(passkey)
            try:
                s.flush()
            except IntegrityError as err:
                raise PasskeyTaken(passkey.id) from err
        s.refresh(user)
        s.expunge(user)
    return user
