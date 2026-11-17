"""scripts/admin.py: `make admin EMAIL=...` makes an existing account an admin (SPEC.md "Admin"),
the only way `users.is_admin` is set."""

import pytest

from app.auth import users
from app.db import UserRow, session_scope, utcnow
from scripts.admin import main


def is_admin(user_id: str) -> bool:
    with session_scope() as s:
        row = s.get(UserRow, user_id)
        assert row is not None
        return row.is_admin


def test_makes_the_account_an_admin(capsys: pytest.CaptureFixture[str]) -> None:
    ana = users.create_user("ana@example.com", password_hash=None)
    bo = users.create_user("bo@example.com", password_hash=None)

    assert main(["ana@example.com"]) == 0

    assert "made ana@example.com an admin" in capsys.readouterr().out
    assert is_admin(ana.id) and not is_admin(bo.id)  # only that account


def test_the_email_is_matched_normalized() -> None:
    ana = users.create_user("ana@example.com", password_hash=None)
    assert main(["  Ana@Example.COM "]) == 0
    assert is_admin(ana.id)


def test_an_unknown_email_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    ana = users.create_user("ana@example.com", password_hash=None)
    assert main(["nobody@example.com"]) == 2
    assert "no account nobody@example.com" in capsys.readouterr().err
    assert not is_admin(ana.id)


def test_making_an_admin_again_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    ana = users.create_user("ana@example.com", password_hash=None)
    assert main(["ana@example.com"]) == 0
    capsys.readouterr()

    assert main(["ana@example.com"]) == 0

    assert "ana@example.com is already an admin" in capsys.readouterr().out
    assert is_admin(ana.id)


def test_a_disabled_account_is_made_admin_and_the_output_says_it_is_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ana = users.create_user("ana@example.com", password_hash=None)
    with session_scope() as s:
        row = s.get(UserRow, ana.id)
        assert row is not None
        row.disabled_at = utcnow()

    assert main(["ana@example.com"]) == 0

    assert "disabled" in capsys.readouterr().out
    assert is_admin(ana.id)
