"""Accept an invite (SPEC.md "Marketing and accounts", Accounts): the invite page reads who
the link is for, then the person adds a passkey, sets a password, or both, which creates the
account and signs it in.

A passkey is registered before the account exists: `passkey/options` picks the new account's
id and binds the challenge to this invite, and `accept` verifies the response and writes the
account, its passkey and the spent invite in one transaction. The link's token is what
authorizes it, the same as for setting the password; nothing is stored until accept succeeds.

Public, under `/api/auth/*`: the link's token is the credential. Like sign-in, the decisions go
to the `app.auth` logger, not a TraceRecorder (see `app/routers/auth.py`).
"""

import logging
import uuid
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request, Response

from app.auth import invites, passkeys, passwords, sessions, users
from app.auth.deps import SESSION_COOKIE, set_session_cookie
from app.auth.sessions import token_hash
from app.db import UserRow, as_utc
from app.routers.auth import to_me
from app.schemas import (
    INVITE_ACCOUNT_EXISTS,
    INVITE_EXPIRED,
    INVITE_NEEDS_SIGN_IN,
    INVITE_UNKNOWN,
    INVITE_USED,
    PASSKEY_NOT_ADDED,
    AcceptInviteRequest,
    InviteInfo,
    Me,
    PasskeyOptions,
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


def _refuse(err: invites.InviteRefused) -> NoReturn:
    if isinstance(err, invites.InviteUnusable):
        status, detail = _UNUSABLE[err.reason]
        log.info("invite refused (%s)", err.reason)
    else:
        status, detail = 409, INVITE_ACCOUNT_EXISTS
        log.info("invite refused (account exists)")
    raise HTTPException(status_code=status, detail=detail) from err


@router.get("/{token}", response_model=InviteInfo, responses=_REFUSALS)
def invite_info(token: str) -> InviteInfo:
    """Who a usable invite is for; 404 unknown, 410 expired or used, 409 account exists."""
    try:
        row = invites.lookup(token)
    except invites.InviteRefused as err:
        _refuse(err)
    return InviteInfo(email=row.email, expires_at=as_utc(row.expires_at))


@router.post("/{token}/passkey/options", response_model=PasskeyOptions, responses=_REFUSALS)
def invite_passkey_options(token: str) -> PasskeyOptions:
    """Start adding a passkey for the account this invite creates: options for
    `startRegistration()`. Finish by posting the result to `accept` as `passkey`."""
    try:
        invite = invites.lookup(token)
    except invites.InviteRefused as err:
        _refuse(err)
    to_be = UserRow(id=uuid.uuid4().hex, email=invite.email)  # not stored until accept
    return passkeys.begin_registration(to_be, invite_hash=token_hash(token))


# Sync on purpose: Argon2 runs in FastAPI's threadpool, not on the event loop.
@router.post(
    "/{token}/accept",
    response_model=Me,
    responses={
        **_REFUSALS,
        400: {"description": f"{PASSKEY_NOT_ADDED} / {INVITE_NEEDS_SIGN_IN}"},
        422: {"description": "The password breaks the rules (as on the reset page)"},
    },
)
def accept_invite(
    token: str, body: AcceptInviteRequest, request: Request, response: Response
) -> Me:
    """Create the account with a passkey, a password, or both, and sign in. A refused link, a
    password that breaks the rules (422, with why), a passkey that doesn't verify or neither
    (400) creates nothing and leaves the link as it was."""
    try:
        invites.lookup(token)  # refuse a bad link before spending an Argon2 hash on it
    except invites.InviteRefused as err:
        _refuse(err)
    if not body.password and body.passkey is None:
        raise HTTPException(status_code=400, detail=INVITE_NEEDS_SIGN_IN)
    if body.password:
        problem = passwords.password_problem(body.password)
        if problem is not None:
            raise HTTPException(status_code=422, detail=problem)
    passkey = None
    if body.passkey is not None:
        passkey = passkeys.verify_registration(
            body.passkey.challenge_id, body.passkey.credential, invite_hash=token_hash(token)
        )
        if passkey is None:
            log.info("invite passkey not added")
            raise HTTPException(status_code=400, detail=PASSKEY_NOT_ADDED)
    password_hash = passwords.hash_password(body.password) if body.password else None
    try:
        user = invites.accept(token, password_hash=password_hash, passkey=passkey)
    except invites.PasskeyTaken as err:
        log.info("invite passkey not added (already registered)")
        raise HTTPException(status_code=400, detail=PASSKEY_NOT_ADDED) from err
    except invites.InviteRefused as err:
        _refuse(err)
    user = users.record_login(user.id, new_hash=None)
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        sessions.delete(old)  # someone else's session in this browser ends here
    set_session_cookie(response, sessions.create(user.id))
    log.info("invite accepted user=%s", user.id)
    return to_me(user)
