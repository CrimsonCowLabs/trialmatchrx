"""Sign in with email and password or a passkey, add, list and remove passkeys, see who's
signed in, sign out (here or everywhere), set or change your password, and set a new password
with a reset link (SPEC.md "Marketing and accounts").

Sign-in isn't an agent run, so its decisions (throttled, which failure, success) go to the
`app.auth` logger rather than a TraceRecorder: a trace needs a run row and belongs in the trace
UI, and an auth event in there would be noise and would leak who tried which email.
"""

import logging
import threading
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth import account, passkeys, passwords, resets, sessions, throttle, users
from app.auth.client_ip import request_ip
from app.auth.deps import (
    SESSION_COOKIE,
    clear_session_cookie,
    require_user,
    set_session_cookie,
)
from app.db import PasskeyRow, UserRow
from app.schemas import (
    LAST_SIGN_IN_METHOD,
    LOGIN_FAILED,
    LOGIN_THROTTLED,
    PASSKEY_NOT_ADDED,
    PASSKEY_NOT_FOUND,
    PASSWORD_CHANGE_THROTTLED,
    PASSWORD_WRONG,
    RESET_DISABLED,
    RESET_EXPIRED,
    RESET_UNKNOWN,
    RESET_USED,
    ChangePasswordRequest,
    LoginRequest,
    Me,
    PasskeyInfo,
    PasskeyLoginRequest,
    PasskeyOptions,
    PasskeyRegisterRequest,
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
    _start_session(request, response, user.id)
    log.info("login ok user=%s ip=%s", user.id, ip)
    return to_me(user)


def _start_session(request: Request, response: Response, user_id: str) -> None:
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        sessions.delete(old)  # signing in again replaces this browser's session
    set_session_cookie(response, sessions.create(user_id))


@router.post("/passkey/login/options", response_model=PasskeyOptions)
def passkey_login_options() -> PasskeyOptions:
    """Start a passkey sign-in: the options for `startAuthentication()` (button or autofill)."""
    return passkeys.begin_login()


@router.post(
    "/passkey/login/verify",
    response_model=Me,
    responses={401: {"description": LOGIN_FAILED}, 429: {"description": LOGIN_THROTTLED}},
)
def passkey_login_verify(body: PasskeyLoginRequest, request: Request, response: Response) -> Me:
    """Finish a passkey sign-in; `credential: null` reports a cancel. Failures share the
    password sign-in's 401 and throttle: each counts against the IP, and against the passkey
    owner's email when the passkey is known."""
    ip = request_ip(request)
    claimed = passkeys.claimed_by(body.credential)
    email = claimed.user.email if claimed.user is not None else ""
    with _attempt_lock:
        if throttle.is_throttled(email, ip):
            passkeys.finish_login(body.challenge_id, None, claimed)  # spend the challenge
            log.info("passkey login throttled ip=%s", ip)
            raise HTTPException(status_code=429, detail=LOGIN_THROTTLED)
        user, failure = passkeys.finish_login(body.challenge_id, body.credential, claimed)
        if user is None:
            throttle.record_failure(email, ip)
            log.info("passkey login failed (%s) ip=%s", failure, ip)
            raise HTTPException(status_code=401, detail=LOGIN_FAILED)
    user = users.record_login(user.id, new_hash=None)
    _start_session(request, response, user.id)
    log.info("passkey login ok user=%s ip=%s", user.id, ip)
    return to_me(user)


def to_passkey_info(row: PasskeyRow) -> PasskeyInfo:
    return PasskeyInfo(id=row.id, created_at=row.created_at, last_used_at=row.last_used_at)


@router.get(
    "/passkeys", response_model=list[PasskeyInfo], responses={401: {"description": "Not signed in"}}
)
def list_passkeys(user: Annotated[UserRow, Depends(require_user)]) -> list[PasskeyInfo]:
    """The signed-in account's passkeys, oldest first."""
    return [to_passkey_info(p) for p in passkeys.list_for_user(user.id)]


@router.delete(
    "/passkeys/{passkey_id}",
    status_code=204,
    responses={
        401: {"description": "Not signed in"},
        404: {"description": PASSKEY_NOT_FOUND},
        409: {"description": LAST_SIGN_IN_METHOD},
    },
)
def remove_passkey(passkey_id: str, user: Annotated[UserRow, Depends(require_user)]) -> None:
    """Remove one of your passkeys. Someone else's, or an unknown id, is 404. Your last way
    to sign in (no password and no other passkey) is 409, and nothing is removed."""
    try:
        account.remove_passkey(user.id, passkey_id)
    except account.PasskeyNotFound:
        raise HTTPException(status_code=404, detail=PASSKEY_NOT_FOUND) from None
    except account.LastSignInMethod:
        log.info("passkey not removed (last sign-in method) user=%s", user.id)
        raise HTTPException(status_code=409, detail=LAST_SIGN_IN_METHOD) from None
    log.info("passkey removed user=%s", user.id)


@router.post(
    "/passkey/register/options",
    response_model=PasskeyOptions,
    responses={401: {"description": "Not signed in"}},
)
def passkey_register_options(user: Annotated[UserRow, Depends(require_user)]) -> PasskeyOptions:
    """Start adding a passkey to the signed-in account: options for `startRegistration()`."""
    return passkeys.begin_registration(user)


@router.post(
    "/passkey/register/verify",
    status_code=201,
    response_model=PasskeyInfo,
    responses={400: {"description": PASSKEY_NOT_ADDED}, 401: {"description": "Not signed in"}},
)
def passkey_register_verify(
    body: PasskeyRegisterRequest, user: Annotated[UserRow, Depends(require_user)]
) -> PasskeyInfo:
    """Finish adding a passkey. Any problem (expired challenge, bad response, wrong origin) is
    the same 400, and nothing is stored."""
    row = passkeys.finish_registration(user.id, body.challenge_id, body.credential)
    if row is None:
        log.info("passkey not added user=%s", user.id)
        raise HTTPException(status_code=400, detail=PASSKEY_NOT_ADDED)
    log.info("passkey added user=%s", user.id)
    return to_passkey_info(row)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    """Sign out: delete this browser's session and clear the cookie. Fine when signed out."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sessions.delete(token)
    clear_session_cookie(response)


@router.post(
    "/logout-everywhere", status_code=204, responses={401: {"description": "Not signed in"}}
)
def logout_everywhere(response: Response, user: Annotated[UserRow, Depends(require_user)]) -> None:
    """Sign out everywhere: end every session of the signed-in account, this one included,
    and clear this browser's cookie."""
    ended = account.end_all_sessions(user.id)
    clear_session_cookie(response)
    log.info("signed out everywhere user=%s sessions=%d", user.id, ended)


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


# ---- The account page (/app/account) ------------------------------------------------------


# Sync for the same reason as login: Argon2 runs in the threadpool.
@router.post(
    "/password",
    response_model=Me,
    responses={
        401: {"description": "Not signed in"},
        403: {"description": PASSWORD_WRONG},
        422: {"description": "The new password breaks the rules"},
        429: {"description": PASSWORD_CHANGE_THROTTLED},
    },
)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: Annotated[UserRow, Depends(require_user)],
) -> Me:
    """Set a password (an account without one) or change it (the current one is required).
    A new password that breaks the rules is a 422 with the reason. A wrong current password
    is a 403 and counts toward the account's own password-change limit (not sign-in's, so a
    stolen session can't lock the owner out); once over it, a 429 without checking. Ends
    every other session; this one stays."""
    problem = passwords.password_problem(body.new_password)
    if problem is not None:
        raise HTTPException(status_code=422, detail=problem)
    ip = request_ip(request)
    if user.password_hash is not None:
        with _attempt_lock:
            if throttle.password_change_throttled(user.id):
                log.info("password change throttled user=%s ip=%s", user.id, ip)
                raise HTTPException(status_code=429, detail=PASSWORD_CHANGE_THROTTLED)
            ok, _ = passwords.verify_password(user.password_hash, body.current_password or "")
            if not ok:
                throttle.record_password_change_failure(user.id)
                log.info("password change: wrong current password user=%s ip=%s", user.id, ip)
                raise HTTPException(status_code=403, detail=PASSWORD_WRONG)
    try:
        updated = account.set_password(
            user.id,
            passwords.hash_password(body.new_password),
            expected=user.password_hash,
            keep_session=request.cookies.get(SESSION_COOKIE),
        )
    except account.PasswordChangedMeanwhile:
        # Set or changed by another request since this one checked: the current password
        # given here (or its absence) wasn't checked against it. Not a guess, so no strike.
        log.info("password change: changed meanwhile user=%s", user.id)
        raise HTTPException(status_code=403, detail=PASSWORD_WRONG) from None
    log.info("password %s user=%s", "changed" if user.password_hash else "set", user.id)
    return to_me(updated)
