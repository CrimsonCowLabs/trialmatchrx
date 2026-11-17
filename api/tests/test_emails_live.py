"""One real email through Resend, to EMAIL_REPLY_TO. Run with `uv run pytest -m live` and
RESEND_API_KEY set."""

import pytest

from app.config import get_settings
from app.emails import render
from app.emails.sender import ResendSender


@pytest.mark.live
def test_a_real_invite_email_is_sent() -> None:
    s = get_settings()
    if not s.resend_api_key:
        pytest.skip("RESEND_API_KEY is not set")
    subject, text, html = render(
        "invite",
        note="Hi Aaron, this is the live test.",
        link=f"{s.app_url}/invite/live-test-not-a-real-token",
        expires_days=7,
    )
    sender = ResendSender(s.resend_api_key, s.email_from, s.email_reply_to)

    result = sender.send(s.email_reply_to, f"[live test] {subject}", text, html)

    assert result.sent, result.error
    assert result.id
