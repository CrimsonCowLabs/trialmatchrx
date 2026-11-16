"""scripts/disable_user.py: `make disable-user EMAIL=...` ends the account's sessions and blocks
sign-in, keeping the row (so a run's `created_by` still resolves)."""

import httpx
import pytest

from app.auth import passwords, sessions, users
from app.db import UserRow, session_scope
from app.main import app
from app.schemas import LOGIN_FAILED
from scripts.disable_user import main

PASSWORD = "correct horse battery staple"


def make_user(email: str = "ana@example.com") -> str:
    return users.create_user(email, password_hash=passwords.hash_password(PASSWORD)).id


def test_disabling_ends_sessions_and_keeps_the_row(capsys: pytest.CaptureFixture[str]) -> None:
    user_id = make_user()
    other_id = make_user("bo@example.com")
    mine = [sessions.create(user_id), sessions.create(user_id)]
    theirs = sessions.create(other_id)

    assert main(["ana@example.com"]) == 0

    out = capsys.readouterr().out
    assert "disabled ana@example.com" in out and "2 sessions ended" in out
    assert all(sessions.resolve(token) is None for token in mine)
    assert sessions.resolve(theirs) is not None  # only that user's sessions
    with session_scope() as s:
        row = s.get(UserRow, user_id)
        assert row is not None and row.disabled_at is not None


async def test_a_disabled_user_cannot_sign_in() -> None:
    make_user()
    assert main(["ana@example.com"]) == 0
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
        headers={"X-Requested-With": "fetch"},
    ) as c:
        response = await c.post(
            "/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD}
        )
    assert (response.status_code, response.json()) == (401, {"detail": LOGIN_FAILED})


def test_the_email_is_matched_normalized() -> None:
    user_id = make_user()
    assert main(["  Ana@Example.COM "]) == 0
    with session_scope() as s:
        row = s.get(UserRow, user_id)
        assert row is not None and row.disabled_at is not None


def test_an_unknown_email_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    make_user()
    assert main(["nobody@example.com"]) == 2
    assert "no account nobody@example.com" in capsys.readouterr().err


def test_disabling_again_says_so_and_keeps_the_first_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    user_id = make_user()
    assert main(["ana@example.com"]) == 0
    with session_scope() as s:
        row = s.get(UserRow, user_id)
        assert row is not None
        first = row.disabled_at
    capsys.readouterr()

    assert main(["ana@example.com"]) == 0

    assert "already disabled" in capsys.readouterr().out
    with session_scope() as s:
        row = s.get(UserRow, user_id)
        assert row is not None and row.disabled_at == first
