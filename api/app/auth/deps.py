"""The session cookie, the gate in front of every `/api` route, and the dependencies that read
the session.

`require_session` is the app-wide gate (SPEC.md "Enforcement"): `app.main` installs it on the
FastAPI app, so every route, including any added later, needs a session unless `is_public`
names it. `signed_in_user` hands a gated route the user the gate found. `require_user` and
`current_user` are for the public `/api/auth/*` routes, which the gate leaves alone.
`require_admin` guards `/api/admin/*` (SPEC.md "Admin") and answers 404 to anyone else; the gate
skips that prefix so a signed-out caller gets the same 404. All of them
resolve the cookie through `app/auth/sessions.py`, which rolls the 30-day expiry, and re-send
the cookie when it rolled so the browser's copy keeps the same lifetime as the row.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from app.auth import sessions
from app.config import get_settings
from app.db import UserRow

SESSION_COOKIE = "tmrx_session"

# The only `/api` routes open without a session (SPEC.md "Enforcement"). The one place to change
# it; tests/test_require_login.py calls every other registered route signed out and expects 401.
PUBLIC_ROUTES = frozenset(
    {
        ("GET", "/api/health"),
        ("POST", "/api/access-requests"),  # request access (#8)
    }
)
PUBLIC_PREFIX = "/api/auth/"  # sign-in, invites, reset links: used before there's a session
# `/api/admin/*` answers 404, not the gate's 401, to anyone but an admin, signed out included
# (SPEC.md "Enforcement"), so the gate leaves it to `require_admin`, which the admin router
# installs on every route. The trailing slash keeps e.g. `/api/administrator` gated.
ADMIN_PREFIX = "/api/admin/"


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


def is_public(method: str, path: str) -> bool:
    return (method, path) in PUBLIC_ROUTES or path.startswith(PUBLIC_PREFIX)


def is_admin_path(path: str) -> bool:
    """Guarded by `require_admin` instead of the session gate."""
    return path.startswith(ADMIN_PREFIX)


def require_session(request: Request, response: Response) -> None:
    """The app-wide gate: 401 without a valid session, except on a public route. Public routes
    aren't looked up at all, so e.g. sign-out never gets a rolled cookie beside its cleared
    one. An admin route is left to `require_admin`. The user is kept on `request.state` for
    `signed_in_user`."""
    path = request.url.path
    if is_public(request.method, path) or is_admin_path(path):
        return
    request.state.user = require_user(current_user(request, response))


def signed_in_user(request: Request) -> UserRow:
    """The user `require_session` let through. Only on a gated route: a public one has none."""
    user: UserRow | None = getattr(request.state, "user", None)
    if user is None:
        raise RuntimeError(f"signed_in_user on public route {request.url.path}: use require_user")
    return user


def require_admin(request: Request, response: Response) -> UserRow:
    """The signed-in admin, or 404 `Not Found` (SPEC.md "Admin" and "Enforcement"): a non-admin,
    a disabled account and no session all get the same answer as an unknown route, so the admin
    API doesn't reveal itself. Reuses the user the gate found, else resolves the cookie."""
    user: UserRow | None = getattr(request.state, "user", None) or current_user(request, response)
    if user is None or not user.is_admin:
        raise HTTPException(status_code=404, detail="Not Found")
    return user
