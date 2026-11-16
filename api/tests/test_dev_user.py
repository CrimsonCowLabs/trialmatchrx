"""scripts/dev_user.py: `make dev-user` makes (or resets) the local sign-in account, and refuses
unless the database is the local dev one: a SQLite file inside the repo's api/ directory."""

from pathlib import Path

import pytest

from app import db
from app.auth import passwords, users
from scripts.dev_user import DEV_EMAIL, DEV_PASSWORD, is_local_dev_db, main

API_DIR = Path("/repo/api")


def test_local_means_a_sqlite_file_inside_api() -> None:
    assert is_local_dev_db("sqlite:////repo/api/app.db", API_DIR)
    assert is_local_dev_db("sqlite:////repo/api/data/dev.db", API_DIR)


def test_anything_else_is_not_local() -> None:
    assert not is_local_dev_db("sqlite:////data/app.db", API_DIR)  # the prod volume
    assert not is_local_dev_db("sqlite:////repo/app.db", API_DIR)  # beside api/, not in it
    assert not is_local_dev_db("sqlite:////repo/api/../app.db", API_DIR)
    assert not is_local_dev_db("sqlite:////repo/api-other/app.db", API_DIR)
    assert not is_local_dev_db("sqlite://", API_DIR)  # in-memory
    assert not is_local_dev_db("postgresql://u@db/app", API_DIR)


def test_refuses_on_a_database_outside_api(capsys: pytest.CaptureFixture[str]) -> None:
    # The per-test database is in pytest's tmp dir, not in api/.
    assert main([]) == 2
    assert "refusing" in capsys.readouterr().err
    assert users.find_by_email(DEV_EMAIL) is None


def test_creates_the_account_and_prints_the_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([], api_dir=tmp_path) == 0  # the per-test database counts as local here
    out = capsys.readouterr().out
    assert DEV_EMAIL in out and DEV_PASSWORD in out
    user = users.find_by_email(DEV_EMAIL)
    assert user is not None and user.password_hash is not None
    assert passwords.verify_password(user.password_hash, DEV_PASSWORD).ok


def test_the_known_password_passes_the_rules() -> None:
    assert passwords.password_problem(DEV_PASSWORD) is None


def test_running_again_keeps_one_account_and_restores_it(tmp_path: Path) -> None:
    assert main([], api_dir=tmp_path) == 0
    first = users.find_by_email(DEV_EMAIL)
    assert first is not None
    with db.session_scope() as s:  # someone changed the password and disabled it
        row = s.get(db.UserRow, first.id)
        assert row is not None
        row.password_hash = passwords.hash_password("something else entirely")
        row.disabled_at = db.utcnow()
    assert main([], api_dir=tmp_path) == 0
    again = users.find_by_email(DEV_EMAIL)
    assert again is not None and again.id == first.id
    assert again.disabled_at is None
    assert again.password_hash is not None
    assert passwords.verify_password(again.password_hash, DEV_PASSWORD).ok
