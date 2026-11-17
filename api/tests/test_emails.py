"""Email templates (`app/emails/*.md`) and the Resend sender (SPEC.md "Admin", Sending).
Resend is an httpx MockTransport; nothing leaves the box."""

import json
import logging

import httpx
import pytest

from app.config import get_settings
from app.emails import EmailTemplateError, load_template, render
from app.emails.sender import (
    RESEND_URL,
    LogSender,
    ResendSender,
    SendResult,
    get_sender,
)

INVITE_VARS = {"note": "Hi Ana,", "link": "https://tmrx.example/invite/abc", "expires_days": 7}
REQUEST_VARS = {
    "name": "Ana Silva",
    "email": "ana@acme-pharma.example",
    "organization": "Acme Pharma",
    "role": "sponsor",
    "message": "We run two T2D trials.",
    "admin_url": "https://tmrx.example/app/admin",
}


@pytest.mark.parametrize(
    ("name", "version", "names"),
    [
        ("invite", "invite-v1", set(INVITE_VARS)),
        ("new_request", "new-request-v1", set(REQUEST_VARS)),
    ],
)
def test_each_template_has_a_version_and_exactly_its_placeholders(
    name: str, version: str, names: set[str]
) -> None:
    t = load_template(name)
    assert t.version == version
    assert t.placeholders() == names


def test_the_invite_carries_the_note_link_and_expiry() -> None:
    subject, text, html = render("invite", **INVITE_VARS)
    assert subject == "Your TrialMatch Rx invite"
    assert text.startswith("Hi Ana,\n\n")
    assert "https://tmrx.example/invite/abc" in text and "7 days" in text
    assert '<a href="https://tmrx.example/invite/abc">' in html
    assert "{{" not in text + html


def test_an_invite_without_a_note_leaves_no_gap() -> None:
    _, text, html = render("invite", **{**INVITE_VARS, "note": ""})
    assert text.startswith("You're invited")
    assert "\n\n\n" not in text
    assert html.startswith("<p>You're invited")
    assert "<p></p>" not in html


def test_html_escapes_every_value_and_keeps_line_breaks() -> None:
    _, text, html = render(
        "new_request",
        **{
            **REQUEST_VARS,
            "name": '<script>alert("x")</script>',
            "message": "line one\n<b>line two</b>",
        },
    )
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "line one<br>\n&lt;b&gt;line two&lt;/b&gt;" in html
    assert '<script>alert("x")</script>' in text  # plain text is not HTML


def test_the_new_request_subject_is_one_line() -> None:
    subject, text, _ = render("new_request", **{**REQUEST_VARS, "name": "Ana\nSilva"})
    assert subject == "Access request: Ana Silva (Acme Pharma)"
    for value in ("ana@acme-pharma.example", "sponsor", "We run two T2D trials."):
        assert value in text
    assert "https://tmrx.example/app/admin" in text


def test_a_missing_value_is_an_error() -> None:
    with pytest.raises(EmailTemplateError, match="link"):
        render("invite", note="", expires_days=7)


def resend(handler: httpx.MockTransport) -> ResendSender:
    return ResendSender("re_test", "TM <noreply@tm.example>", "reply@tm.example", transport=handler)


def test_resend_gets_one_authorized_post_and_the_id_comes_back() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "em_123"})

    result = resend(httpx.MockTransport(handler)).send(
        "ana@example.com", "Hi", "text body", "<p>html body</p>"
    )
    assert result == SendResult("sent", id="em_123")
    assert result.sent
    (req,) = seen
    assert str(req.url) == RESEND_URL
    assert req.headers["Authorization"] == "Bearer re_test"
    assert json.loads(req.content) == {
        "from": "TM <noreply@tm.example>",
        "to": ["ana@example.com"],
        "subject": "Hi",
        "text": "text body",
        "html": "<p>html body</p>",
        "reply_to": "reply@tm.example",
    }


def test_an_explicit_reply_to_wins_over_the_default() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "em_1"})

    resend(httpx.MockTransport(handler)).send("a@x.example", "s", "t", "h", reply_to="b@x.example")
    assert bodies[0]["reply_to"] == "b@x.example"


def test_a_resend_refusal_is_a_failure_with_its_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422, json={"name": "validation_error", "message": "The `to` field is invalid."}
        )

    result = resend(httpx.MockTransport(handler)).send("bad", "s", "t", "h")
    assert result == SendResult("failed", error="Resend 422: The `to` field is invalid.")
    assert not result.sent


def test_a_refusal_without_json_still_says_what_happened() -> None:
    result = resend(httpx.MockTransport(lambda r: httpx.Response(502, text="bad gateway"))).send(
        "a@x.example", "s", "t", "h"
    )
    assert result == SendResult("failed", error="Resend 502: Bad Gateway")


def test_an_unreachable_resend_is_a_failure_not_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    result = resend(httpx.MockTransport(handler)).send("a@x.example", "s", "t", "h")
    assert result.status == "failed"
    assert result.error is not None and "timed out" in result.error


def test_without_a_key_the_email_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "resend_api_key", None)
    sender = get_sender()
    assert isinstance(sender, LogSender)
    with caplog.at_level(logging.INFO, logger="app.emails"):
        result = sender.send("ana@example.com", "Invite", "open https://tm.example/i/abc", "<p/>")
    assert result == SendResult("logged")
    assert "https://tm.example/i/abc" in caplog.text


def test_with_a_key_the_sender_is_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_test")
    assert isinstance(get_sender(), ResendSender)
