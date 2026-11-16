"""Passkeys with py_webauthn (SPEC.md "Marketing and accounts", Passkeys).

Each ceremony is begin + finish. `begin_*` stores a random challenge in `webauthn_challenges`
and returns its id with the options JSON for the browser; `finish_*` consumes that challenge
(single-use, `CHALLENGE_TTL`) and verifies what the browser sent back against the relying-party
ID and origin from settings.

Passkeys are the whole sign-in (no password beside them), so both ceremonies require user
verification (the device's PIN or biometric), and new credentials must be discoverable
(resident keys) so the login page can offer them from autofill without an email first.

Adding a passkey takes a user id, not a session, so the invite page (#3) can reuse it for the
account it's creating.
"""

import datetime as dt
import json
import secrets
from typing import Any, Literal, NamedTuple

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel import delete as sql_delete
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import get_settings
from app.db import PasskeyRow, UserRow, WebAuthnChallengeRow, as_utc, session_scope, utcnow
from app.schemas import PasskeyOptions

RP_NAME = "TrialMatch Rx"
CHALLENGE_TTL = dt.timedelta(minutes=5)

Kind = Literal["register", "login"]

# What a malformed or forged browser response can raise inside py_webauthn: its own errors,
# plus the plain ones its parsers let through on odd shapes (a number where a string goes).
_BAD_RESPONSE = (WebAuthnException, ValueError, TypeError, KeyError, AttributeError)


# Outstanding challenges kept at most; past it the oldest go. Starting a passkey sign-in needs
# no session, so without a cap a burst of requests could grow the table for CHALLENGE_TTL.
MAX_CHALLENGES = 1000


def _new_challenge(kind: Kind, challenge: bytes, user_id: str | None) -> str:
    """Store a challenge; also drops expired ones, and the oldest past MAX_CHALLENGES, so
    abandoned ceremonies don't pile up."""
    now = utcnow()
    challenge_id = secrets.token_urlsafe(24)
    with session_scope() as s:
        s.exec(
            sql_delete(WebAuthnChallengeRow).where(
                col(WebAuthnChallengeRow.created_at) <= now - CHALLENGE_TTL
            )
        )
        newest = (
            select(WebAuthnChallengeRow.id)
            .order_by(col(WebAuthnChallengeRow.created_at).desc())
            .limit(MAX_CHALLENGES - 1)
        )
        s.exec(sql_delete(WebAuthnChallengeRow).where(col(WebAuthnChallengeRow.id).not_in(newest)))
        s.add(
            WebAuthnChallengeRow(
                id=challenge_id, kind=kind, challenge=challenge, user_id=user_id, created_at=now
            )
        )
    return challenge_id


def _consume_challenge(challenge_id: str, kind: Kind, user_id: str | None) -> bytes | None:
    """The stored challenge, deleted on read whatever happens next; None when it's unknown,
    expired, for the other ceremony, or started by someone else."""
    with session_scope() as s:
        row = s.get(WebAuthnChallengeRow, challenge_id)
        if row is None:
            return None
        # A DELETE that counts its rows, not session.delete: of two requests racing with the
        # same id, only the one that removed the row may use it.
        gone = s.exec(
            sql_delete(WebAuthnChallengeRow).where(col(WebAuthnChallengeRow.id) == challenge_id)
        )
        if gone.rowcount != 1:
            return None
        if row.kind != kind or row.user_id != user_id:
            return None
        if utcnow() - as_utc(row.created_at) >= CHALLENGE_TTL:
            return None
        return row.challenge


def _options_json(options: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(options_to_json(options))
    return parsed


def _transports(values: list[str]) -> list[AuthenticatorTransport]:
    known = {t.value for t in AuthenticatorTransport}
    return [AuthenticatorTransport(v) for v in values if v in known]


def list_for_user(user_id: str) -> list[PasskeyRow]:
    """The user's passkeys, oldest first."""
    with session_scope() as s:
        rows = list(
            s.exec(
                select(PasskeyRow)
                .where(PasskeyRow.user_id == user_id)
                .order_by(col(PasskeyRow.created_at))
            ).all()
        )
        for row in rows:
            s.expunge(row)
        return rows


# ---- Adding a passkey ---------------------------------------------------------------------


def begin_registration(user: UserRow) -> PasskeyOptions:
    settings = get_settings()
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=RP_NAME,
        user_name=user.email,
        user_display_name=user.email,
        # The WebAuthn user handle: the opaque account id, never the email.
        user_id=user.id.encode(),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        # The browser refuses to make a second passkey on a device that already has one here.
        exclude_credentials=[
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(p.id), transports=_transports(p.transports)
            )
            for p in list_for_user(user.id)
        ],
    )
    return PasskeyOptions(
        challenge_id=_new_challenge("register", options.challenge, user.id),
        options=_options_json(options),
    )


def finish_registration(
    user_id: str, challenge_id: str, credential: dict[str, Any]
) -> PasskeyRow | None:
    """Verify the browser's registration response and store the passkey; None (nothing
    stored) when the challenge or the response doesn't check out."""
    challenge = _consume_challenge(challenge_id, "register", user_id)
    if challenge is None:
        return None
    settings = get_settings()
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            require_user_verification=True,
        )
    except _BAD_RESPONSE:
        return None
    response = credential.get("response")
    transports = response.get("transports") if isinstance(response, dict) else None
    row = PasskeyRow(
        id=bytes_to_base64url(verified.credential_id),
        user_id=user_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=[t for t in transports if isinstance(t, str)]
        if isinstance(transports, list)
        else [],
    )
    try:
        with session_scope() as s:
            s.add(row)
            s.flush()
            s.refresh(row)
            s.expunge(row)
    except IntegrityError:
        return None  # the same credential twice (excludeCredentials normally prevents it)
    return row


# ---- Signing in ---------------------------------------------------------------------------


def begin_login() -> PasskeyOptions:
    """No allowCredentials: the browser offers whichever passkey for this site it holds (the
    button, or autofill on the email field), so nothing reveals which accounts exist."""
    options = generate_authentication_options(
        rp_id=get_settings().webauthn_rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return PasskeyOptions(
        challenge_id=_new_challenge("login", options.challenge, None),
        options=_options_json(options),
    )


class Claimed(NamedTuple):
    """Who a sign-in response says it is, looked up before verifying it so a failure can
    count against that account's email in the throttle."""

    passkey: PasskeyRow | None
    user: UserRow | None


def claimed_by(credential: dict[str, Any] | None) -> Claimed:
    raw_id = credential.get("id") if credential is not None else None
    if not isinstance(raw_id, str):
        return Claimed(None, None)
    with session_scope() as s:
        passkey = s.get(PasskeyRow, raw_id)
        if passkey is None:
            return Claimed(None, None)
        user = s.get(UserRow, passkey.user_id)
        s.expunge(passkey)
        if user is not None:
            s.expunge(user)
        return Claimed(passkey, user)


def finish_login(
    challenge_id: str, credential: dict[str, Any] | None, claimed: Claimed
) -> tuple[UserRow | None, str | None]:
    """(the user, None) on success, else (None, why) with the reason for the log only. The
    challenge is consumed either way. On success the passkey's counter and last use move."""
    challenge = _consume_challenge(challenge_id, "login", None)
    if credential is None:
        return None, "cancelled"
    if challenge is None:
        return None, "unknown or expired challenge"
    passkey, user = claimed
    if passkey is None or user is None:
        return None, "unknown passkey"
    response = credential.get("response")
    user_handle = response.get("userHandle") if isinstance(response, dict) else None
    if user_handle and user_handle != bytes_to_base64url(user.id.encode()):
        return None, "user handle mismatch"
    settings = get_settings()
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except _BAD_RESPONSE:
        return None, "bad response"
    if user.disabled_at is not None:
        return None, "disabled"
    with session_scope() as s:
        row = s.get(PasskeyRow, passkey.id)
        if row is not None:
            row.sign_count = verified.new_sign_count
            row.last_used_at = utcnow()
    return user, None
