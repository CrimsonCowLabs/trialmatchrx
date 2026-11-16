"""scripts/reset_link.py: `make reset-link EMAIL=...` prints a one-time password-reset link
(1 hour), and refuses for an unknown or disabled account."""

import re

import pytest

from app.auth import passwords, users
from app.db import UserRow, session_scope, utcnow
from scripts.reset_link import main

LINK = re.compile(r"(https?://\S+/reset/(\S+))")


def make_user(email: str = "ana@example.com") -> UserRow:
    return users.create_user(email, password_hash=passwords.hash_password("old password 123"))


def test_prints_a_reset_link_for_the_account(capsys: pytest.CaptureFixture[str]) -> None:
    make_user()
    assert main(["Ana@Example.com"]) == 0
    out = capsys.readouterr().out
    match = LINK.search(out)
    assert match is not None, out
    assert match.group(1).startswith("http://localhost:3045/reset/")
    assert len(match.group(2)) >= 40  # 256 random bits, url-safe
    assert "1 hour" in out


def test_each_run_prints_a_new_link(capsys: pytest.CaptureFixture[str]) -> None:
    make_user()
    main(["ana@example.com"])
    main(["ana@example.com"])
    links = LINK.findall(capsys.readouterr().out)
    assert len(links) == 2 and links[0] != links[1]


def test_refuses_an_unknown_email(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["nobody@example.com"]) == 2
    captured = capsys.readouterr()
    assert "no account" in captured.err
    assert LINK.search(captured.out) is None


def test_refuses_a_disabled_account(capsys: pytest.CaptureFixture[str]) -> None:
    user = make_user()
    with session_scope() as s:
        row = s.get(UserRow, user.id)
        assert row is not None
        row.disabled_at = utcnow()
    assert main(["ana@example.com"]) == 2
    captured = capsys.readouterr()
    assert "disabled" in captured.err
    assert LINK.search(captured.out) is None
