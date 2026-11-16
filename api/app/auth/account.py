"""What you change about your own account on `/app/account` (SPEC.md "Marketing and accounts"):
your password, your passkeys and your sessions. The routes in `app/routers/auth.py` check the
password rules and the throttle; this module makes the changes, each in one transaction.
"""

from app.auth import sessions
from app.db import UserRow, session_scope


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
