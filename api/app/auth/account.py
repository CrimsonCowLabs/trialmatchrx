"""What you change about your own account on `/app/account` (SPEC.md "Marketing and accounts"):
your password, your passkeys and your sessions. The routes in `app/routers/auth.py` check the
password rules and the throttle; this module makes the changes, each in one transaction.

An account always keeps a way to sign in: a password, or at least one passkey. Nothing here
removes a password, so the only way to lose the last one is removing the last passkey of a
passkey-only account, and `remove_passkey` refuses that.
"""

from sqlalchemy import func, or_
from sqlmodel import col, exists, select
from sqlmodel import delete as sql_delete

from app.auth import sessions
from app.db import PasskeyRow, UserRow, session_scope


def set_password(user_id: str, new_hash: str, *, keep_session: str | None) -> UserRow:
    """Store `new_hash` as the password and end every other session of the user (all but the
    one whose token is `keep_session`), together."""
    with session_scope() as s:
        user = s.get(UserRow, user_id)
        if user is None:
            raise LookupError(f"no user {user_id!r}")
        user.password_hash = new_hash
        sessions.end_user_sessions(s, user_id, keep=keep_session)
        s.flush()
        s.refresh(user)
        s.expunge(user)
    return user


class PasskeyNotFound(Exception):
    """No such passkey on this account (it may be someone else's: the same answer)."""


class LastSignInMethod(Exception):
    """Removing it would leave the account with no way to sign in."""


def remove_passkey(user_id: str, passkey_id: str) -> None:
    """Delete `user_id`'s passkey `passkey_id`, unless it's their last way to sign in (no
    password and no other passkey): LastSignInMethod. PasskeyNotFound when it isn't theirs.

    One conditional DELETE, so the check and the delete can't be split: two requests removing
    a passkey-only account's last two passkeys at once can't both pass."""
    has_password = exists().where(
        col(UserRow.id) == user_id, col(UserRow.password_hash).is_not(None)
    )
    other_passkeys = (
        select(func.count())
        .select_from(PasskeyRow)
        .where(col(PasskeyRow.user_id) == user_id, col(PasskeyRow.id) != passkey_id)
        .scalar_subquery()
    )
    with session_scope() as s:
        gone = s.exec(
            sql_delete(PasskeyRow).where(
                col(PasskeyRow.id) == passkey_id,
                col(PasskeyRow.user_id) == user_id,
                or_(has_password, other_passkeys > 0),
            )
        )
        if gone.rowcount == 1:
            return
        row = s.get(PasskeyRow, passkey_id)
        if row is None or row.user_id != user_id:
            raise PasskeyNotFound
        raise LastSignInMethod
