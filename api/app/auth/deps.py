"""The session cookie and the FastAPI dependencies that read it.

`require_user` is the dependency every signed-in-only route uses (SPEC.md "Enforcement");
`current_user` is the optional form. Both resolve the cookie through `app/auth/sessions.py`,
which rolls the 30-day expiry, and re-send the cookie when it rolled so the browser's copy
keeps the same lifetime as the row.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from app.auth import sessions
from app.config import get_settings
from app.db import UserRow

SESSION_COOKIE = "tmrx_session"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(sessions.SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=get_settings().session_cookie_secure,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=get_settings().session_cookie_secure,
    )


def current_user(request: Request, response: Response) -> UserRow | None:
    """The signed-in user, or None (no cookie, unknown or expired session, disabled user)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    found = sessions.resolve(token)
    if found is None:
        return None
    if found.rolled:
        set_session_cookie(response, token)
    return found.user


def require_user(user: Annotated[UserRow | None, Depends(current_user)]) -> UserRow:
    """The signed-in user, or 401."""
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first")
    return user
