"""The `users` table: look up and create accounts. Emails are matched normalized."""

import uuid

from sqlmodel import select

from app.db import UserRow, session_scope, utcnow


def normalize_email(email: str) -> str:
    """How an email is stored and compared: trimmed and lowercased."""
    return email.strip().lower()


def find_by_email(email: str) -> UserRow | None:
    with session_scope() as s:
        row = s.exec(select(UserRow).where(UserRow.email == normalize_email(email))).first()
        if row is not None:
            s.expunge(row)
        return row


def record_login(user_id: str, *, new_hash: str | None) -> UserRow:
    """Stamp a successful sign-in; store `new_hash` when the old one needed upgrading."""
    with session_scope() as s:
        row = s.get(UserRow, user_id)
        if row is None:
            raise LookupError(f"no user {user_id!r}")
        row.last_login_at = utcnow()
        if new_hash is not None:
            row.password_hash = new_hash
        s.flush()
        s.refresh(row)
        s.expunge(row)
    return row


def create_user(email: str, *, password_hash: str | None) -> UserRow:
    """A new account. `password_hash` None is a passkey-only account (no password sign-in)."""
    row = UserRow(id=uuid.uuid4().hex, email=normalize_email(email), password_hash=password_hash)
    with session_scope() as s:
        s.add(row)
        s.flush()
        s.refresh(row)
        s.expunge(row)
    return row
