"""scripts/invite.py: `make invite EMAIL=...` prints a one-time link to /invite/<token> that
expires after 7 days, and refuses an email that already has an account."""

import pytest

from app.auth import passwords, users
from app.config import get_settings
from scripts.invite import main


def printed_link(out: str) -> str:
    [link] = [w for w in out.split() if "/invite/" in w]
    return link


def test_prints_a_link_to_the_invite_page(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ana@example.com", "--base-url", "https://tmrx.example"]) == 0
    out = capsys.readouterr().out
    link = printed_link(out)
    assert link.startswith("https://tmrx.example/invite/")
    assert len(link.rsplit("/", 1)[1]) >= 43  # 256 bits, url-safe base64
    assert "ana@example.com" in out
    assert "7 days" in out


def test_the_base_url_defaults_to_the_app_url_setting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["ana@example.com"]) == 0
    link = printed_link(capsys.readouterr().out)
    assert link.startswith(f"{get_settings().app_url.rstrip('/')}/invite/")


def test_each_invite_is_a_new_link(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ana@example.com"]) == 0
    first = printed_link(capsys.readouterr().out)
    assert main(["ana@example.com"]) == 0
    assert printed_link(capsys.readouterr().out) != first


def test_refuses_an_email_that_already_has_an_account(
    capsys: pytest.CaptureFixture[str],
) -> None:
    users.create_user("Ana@Example.com", password_hash=passwords.hash_password("x" * 12))
    assert main([" ana@example.COM "]) == 1
    captured = capsys.readouterr()
    assert "already has an account" in captured.err
    assert "/invite/" not in captured.out


def test_refuses_something_that_is_not_an_email(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["not-an-email"]) == 2
    assert "/invite/" not in capsys.readouterr().out
