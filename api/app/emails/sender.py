"""Sending email (SPEC.md "Admin", Sending): the Resend HTTP API through `httpx`, or, without
`RESEND_API_KEY`, a logger.

Callers depend on `get_sender` (FastAPI overrides it in tests) and read the `SendResult`:
`sent`, `logged` (no key: nothing left the box, so show the link to copy) or `failed` (Resend
refused or couldn't be reached; `error` says why). `send` never raises for a send that
didn't go out.

Not an agent run, so like sign-in its outcomes go to a logger rather than a TraceRecorder.
"""

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from app.config import get_settings

log = logging.getLogger("app.emails")

RESEND_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT_S = 10.0

SendStatus = Literal["sent", "logged", "failed"]


@dataclass(frozen=True)
class SendResult:
    status: SendStatus
    id: str | None = None  # Resend's email id, when sent
    error: str | None = None  # why, when failed

    @property
    def sent(self) -> bool:
        return self.status == "sent"


class Sender(Protocol):
    def send(
        self, to: str, subject: str, text: str, html: str, reply_to: str | None = None
    ) -> SendResult: ...


class ResendSender:
    """POSTs one email to Resend. `reply_to=None` uses `default_reply_to`."""

    def __init__(
        self,
        api_key: str,
        email_from: str,
        default_reply_to: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._from = email_from
        self._reply_to = default_reply_to
        self._transport = transport

    def send(
        self, to: str, subject: str, text: str, html: str, reply_to: str | None = None
    ) -> SendResult:
        payload: dict[str, object] = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "text": text,
            "html": html,
        }
        if reply := reply_to or self._reply_to:
            payload["reply_to"] = reply
        try:
            with httpx.Client(transport=self._transport, timeout=RESEND_TIMEOUT_S) as client:
                r = client.post(
                    RESEND_URL, json=payload, headers={"Authorization": f"Bearer {self._api_key}"}
                )
        except httpx.HTTPError as e:
            log.warning("email to %s not sent: %s", to, e)
            return SendResult("failed", error=f"Resend unreachable: {e}")
        if not r.is_success:
            error = _resend_error(r)
            log.warning("email to %s not sent: %s", to, error)
            return SendResult("failed", error=error)
        email_id = _json(r).get("id")
        log.info("email to %s sent id=%s subject=%r", to, email_id, subject)
        return SendResult("sent", id=str(email_id) if email_id else None)


class LogSender:
    """No `RESEND_API_KEY`: the email goes to the log, links and all, and nowhere else."""

    def send(
        self, to: str, subject: str, text: str, html: str, reply_to: str | None = None
    ) -> SendResult:
        log.info(
            "email not sent (no RESEND_API_KEY) to=%s reply_to=%s subject=%r\n%s",
            to,
            reply_to,
            subject,
            text,
        )
        return SendResult("logged")


def _json(r: httpx.Response) -> dict[str, object]:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _resend_error(r: httpx.Response) -> str:
    """Resend's own message (`{"name": ..., "message": ...}`), else the status line."""
    message = _json(r).get("message")
    if isinstance(message, str) and message:
        return f"Resend {r.status_code}: {message}"
    return f"Resend {r.status_code}: {r.reason_phrase or 'error'}"


def get_sender() -> Sender:
    """The app's sender (a FastAPI dependency; tests override it)."""
    s = get_settings()
    if not s.resend_api_key:
        return LogSender()
    return ResendSender(s.resend_api_key, s.email_from, s.email_reply_to)
