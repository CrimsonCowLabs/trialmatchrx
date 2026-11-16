"""Sign in with email and password, see who's signed in, sign out, and set a new password
with a reset link (SPEC.md "Marketing and accounts").

Sign-in isn't an agent run, so its decisions (throttled, which failure, success) go to the
`app.auth` logger rather than a TraceRecorder: a trace needs a run row and belongs in the trace
UI, and an auth event in there would be noise and would leak who tried which email.
"""

import logging
import threading
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth import passwords, resets, sessions, throttle, users
from app.auth.client_ip import request_ip
from app.auth.deps import (
    SESSION_COOKIE,
    clear_session_cookie,
    require_user,
    set_session_cookie,
)
from app.db import UserRow
from app.schemas import (
    LOGIN_FAILED,
    LOGIN_THROTTLED,
    RESET_DISABLED,
    RESET_EXPIRED,
    RESET_UNKNOWN,
    RESET_USED,
    LoginRequest,
    Me,
    ResetLinkCheck,
    ResetLinkInfo,
    ResetPasswordRequest,
)

log = logging.getLogger("app.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


def to_me(user: UserRow) -> Me:
    return Me(
        id=user.id,
        email=user.email,
        has_password=user.password_hash is not None,
        created_at=user.created_at,
    )


class _Checked(NamedTuple):
    user: UserRow | None  # set only when the sign-in succeeded
    failure: str | None  # why it failed, for the log only (never shown)
    new_hash: str | None  # the upgraded hash to store, if the old one is outdated


def _check_password(user: UserRow | None, password: str) -> _Checked:
    """Always does one Argon2 verify, so every outcome takes about as long: an unknown email
    or a passkey-only account verifies against a dummy hash."""
    if user is None or user.password_hash is None:
        passwords.burn_verify(password)
        return _Checked(None, "unknown email" if user is None else "no password set", None)
    ok, new_hash = passwords.verify_password(user.password_hash, password)
    if not ok:
        return _Checked(None, "wrong password", None)
    if user.disabled_at is not None:
        return _Checked(None, "disabled", None)
    return _Checked(user, None, new_hash)


# Check-throttle, verify and record-failure run as one step, or a burst of parallel guesses
# would all pass the check before any failure is written (40 threadpool threads = 40 guesses).
# A process lock is enough: the API runs one worker (api/Dockerfile). Sign-ins queue behind
# one Argon2 verify each, which is fine for an invite-only app.
_attempt_lock = threading.Lock()


# Sync on purpose: Argon2 takes tens of milliseconds, so FastAPI runs this in its threadpool
# instead of blocking the event loop (and every live trace stream with it).
@router.post(
    "/login",
    response_model=Me,
    responses={401: {"description": LOGIN_FAILED}, 429: {"description": LOGIN_THROTTLED}},
)
def login(body: LoginRequest, request: Request, response: Response) -> Me:
    """Sign in. Every failure is the same 401 "Email or password is incorrect"; after 5
    failures in 15 minutes for the email or the IP it's 429 "Try again in a few minutes",
    without checking the password."""
    ip = request_ip(request)
    with _attempt_lock:
        if throttle.is_throttled(body.email, ip):
            log.info("login throttled ip=%s", ip)
            raise HTTPException(status_code=429, detail=LOGIN_THROTTLED)
        checked = _check_password(users.find_by_email(body.email), body.password)
        if checked.user is None:
            throttle.record_failure(body.email, ip)
            log.info("login failed (%s) ip=%s", checked.failure, ip)
            raise HTTPException(status_code=401, detail=LOGIN_FAILED)
    user = users.record_login(checked.user.id, new_hash=checked.new_hash)
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        sessions.delete(old)  # signing in again replaces this browser's session
    set_session_cookie(response, sessions.create(user.id))
    log.info("login ok user=%s ip=%s", user.id, ip)
    return to_me(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    """Sign out: delete this browser's session and clear the cookie. Fine when signed out."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sessions.delete(token)
    clear_session_cookie(response)


@router.get("/me", response_model=Me, responses={401: {"description": "Not signed in"}})
def me(user: Annotated[UserRow, Depends(require_user)]) -> Me:
    """The signed-in account, or 401."""
    return to_me(user)


# Why a reset link can't be used, as the status the page gets with that message.
_RESET_STATUS: dict[resets.RefusalReason, int] = {
    "unknown": 404,
    "expired": 410,
    "used": 410,
    "disabled": 403,
}
_RESET_RESPONSES: dict[int | str, dict[str, str]] = {
    404: {"description": RESET_UNKNOWN},
    410: {"description": f"{RESET_EXPIRED} / {RESET_USED}"},
    403: {"description": RESET_DISABLED},
}


def _refused(exc: resets.ResetRefused) -> HTTPException:
    return HTTPException(status_code=_RESET_STATUS[exc.reason], detail=str(exc))


@router.post("/reset/check", response_model=ResetLinkInfo, responses=_RESET_RESPONSES)
def check_reset_link(body: ResetLinkCheck) -> ResetLinkInfo:
    """Whether a reset link can still be used, and for which account. Changes nothing."""
    try:
        user = resets.check(body.token)
    except resets.ResetRefused as exc:
        log.info("reset link check refused (%s)", exc)
        raise _refused(exc) from None
    return ResetLinkInfo(email=user.email)


# Sync for the same reason as login: Argon2 hashing runs in the threadpool.
@router.post(
    "/reset",
    response_model=Me,
    responses={**_RESET_RESPONSES, 422: {"description": "The password breaks the rules"}},
)
def reset_password(body: ResetPasswordRequest, request: Request, response: Response) -> Me:
    """Set a new password with a reset link (once, within an hour, not for a disabled
    account). Ends every session the user had, this browser's included, then signs this
    browser in with a new one. A password that breaks the rules is a 422 with the reason, and
    the link stays usable."""
    try:
        user = resets.redeem(body.token, body.password)
    except resets.ResetRefused as exc:
        log.info("password reset refused (%s)", exc)
        raise _refused(exc) from None
    except resets.PasswordRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    # Refuse here too, before making a session: the account may have been disabled since the
    # link was redeemed. The password is set either way; a disabled account can't use it.
    current = users.find_by_email(user.email)
    if current is None or current.disabled_at is not None:
        log.info("password reset user=%s: disabled before sign-in", user.id)
        raise HTTPException(status_code=403, detail=RESET_DISABLED)
    user = users.record_login(user.id, new_hash=None)
    set_session_cookie(response, sessions.create(user.id))
    log.info("password reset user=%s ip=%s", user.id, request_ip(request))
    return to_me(user)
