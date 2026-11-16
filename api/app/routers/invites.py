"""Accept an invite (SPEC.md "Marketing and accounts", Accounts): the invite page reads who
the link is for, then the person sets a password, which creates the account and signs it in.

Public, under `/api/auth/*`: the link's token is the credential. Like sign-in, the decisions go
to the `app.auth` logger, not a TraceRecorder (see `app/routers/auth.py`).
"""

import logging
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request, Response

from app.auth import invites, passwords, sessions, users
from app.auth.deps import SESSION_COOKIE, set_session_cookie
from app.routers.auth import to_me
from app.schemas import (
    INVITE_ACCOUNT_EXISTS,
    INVITE_EXPIRED,
    INVITE_UNKNOWN,
    INVITE_USED,
    AcceptInviteRequest,
    InviteInfo,
    Me,
)

log = logging.getLogger("app.auth")

router = APIRouter(prefix="/api/auth/invites", tags=["auth"])

_UNUSABLE: dict[invites.Unusable, tuple[int, str]] = {
    "unknown": (404, INVITE_UNKNOWN),
    "expired": (410, INVITE_EXPIRED),
    "used": (410, INVITE_USED),
}

_REFUSALS: dict[int | str, dict[str, Any]] = {
    404: {"description": INVITE_UNKNOWN},
    409: {"description": INVITE_ACCOUNT_EXISTS},
    410: {"description": f"{INVITE_EXPIRED} / {INVITE_USED}"},
}


def _refuse(err: invites.InviteUnusable | invites.AlreadyHasAccount) -> NoReturn:
    if isinstance(err, invites.AlreadyHasAccount):
        log.info("invite refused (account exists)")
        raise HTTPException(status_code=409, detail=INVITE_ACCOUNT_EXISTS) from err
    status, detail = _UNUSABLE[err.reason]
    log.info("invite refused (%s)", err.reason)
    raise HTTPException(status_code=status, detail=detail) from err


@router.get("/{token}", response_model=InviteInfo, responses=_REFUSALS)
def invite_info(token: str) -> InviteInfo:
    """Who a usable invite is for; 404 unknown, 410 expired or used, 409 account exists."""
    try:
        row = invites.lookup(token)
    except (invites.InviteUnusable, invites.AlreadyHasAccount) as err:
        _refuse(err)
    return InviteInfo(email=row.email, expires_at=row.expires_at)


# Sync on purpose: Argon2 runs in FastAPI's threadpool, not on the event loop.
@router.post(
    "/{token}/accept",
    response_model=Me,
    responses={**_REFUSALS, 400: {"description": "The password breaks the rules"}},
)
def accept_invite(
    token: str, body: AcceptInviteRequest, request: Request, response: Response
) -> Me:
    """Set a password, create the account and sign in. A refused link, or a password that
    breaks the rules (400, with why), creates nothing and leaves the link as it was."""
    try:
        invites.lookup(token)  # refuse a bad link before spending an Argon2 hash on it
    except (invites.InviteUnusable, invites.AlreadyHasAccount) as err:
        _refuse(err)
    problem = passwords.password_problem(body.password)
    if problem is not None:
        raise HTTPException(status_code=400, detail=problem)
    try:
        user = invites.accept(token, password_hash=passwords.hash_password(body.password))
    except (invites.InviteUnusable, invites.AlreadyHasAccount) as err:
        _refuse(err)
    user = users.record_login(user.id, new_hash=None)
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        sessions.delete(old)  # someone else's session in this browser ends here
    set_session_cookie(response, sessions.create(user.id))
    log.info("invite accepted user=%s", user.id)
    return to_me(user)
