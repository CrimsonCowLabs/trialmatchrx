"""scripts/users.py: `make users` lists every account with its created date, last sign-in,
passkey count, whether a password is set and whether it's disabled."""

import datetime as dt

import pytest

from app.auth import users
from app.db import PasskeyRow, UserRow, session_scope
from scripts.users import main

T0 = dt.datetime(2026, 11, 16, 12, 30, tzinfo=dt.UTC)


def set_fields(email: str, **fields: object) -> None:
    found = users.find_by_email(email)
    assert found is not None
    with session_scope() as s:
        row = s.get(UserRow, found.id)
        assert row is not None
        for name, value in fields.items():
            setattr(row, name, value)


def test_lists_each_account_with_its_columns(capsys: pytest.CaptureFixture[str]) -> None:
    users.create_user("ana@example.com", password_hash="$argon2id$fake")
    users.create_user("bo@example.com", password_hash=None)
    set_fields("ana@example.com", created_at=T0, last_login_at=T0 + dt.timedelta(days=1))
    set_fields(
        "bo@example.com",
        created_at=T0 + dt.timedelta(days=2),
        disabled_at=T0 + dt.timedelta(days=3),
    )

    assert main([]) == 0
    lines = capsys.readouterr().out.splitlines()

    assert lines[0].split() == [
        "EMAIL",
        "CREATED",
        "LAST_SIGN_IN",
        "PASSKEYS",
        "PASSWORD",
        "DISABLED",
    ]
    assert lines[1].split() == [
        "ana@example.com",
        "2026-11-16",
        "2026-11-17",
        "12:30",
        "0",
        "yes",
        "no",
    ]
    assert lines[2].split() == [
        "bo@example.com",
        "2026-11-18",
        "never",
        "0",
        "no",
        "2026-11-19",
    ]


def test_counts_each_accounts_passkeys(capsys: pytest.CaptureFixture[str]) -> None:
    ana = users.create_user("ana@example.com", password_hash=None)
    users.create_user("bo@example.com", password_hash=None)
    with session_scope() as s:
        for n in range(2):
            s.add(PasskeyRow(id=f"cred-{n}", user_id=ana.id, public_key=b"key"))
    main([])
    rows = {line.split()[0]: line.split() for line in capsys.readouterr().out.splitlines()[1:]}
    assert rows["ana@example.com"][3] == "2"
    assert rows["bo@example.com"][3] == "0"


def test_oldest_account_first(capsys: pytest.CaptureFixture[str]) -> None:
    users.create_user("new@example.com", password_hash=None)
    users.create_user("old@example.com", password_hash=None)
    set_fields("new@example.com", created_at=T0 + dt.timedelta(days=5))
    set_fields("old@example.com", created_at=T0)

    assert main([]) == 0
    emails = [line.split()[0] for line in capsys.readouterr().out.splitlines()[1:]]
    assert emails == ["old@example.com", "new@example.com"]


def test_no_accounts_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out.strip() == "no accounts"
