"""app/auth/sessions.py: create, resolve, roll, expire and delete sessions. Against the per-test
SQLite file (conftest); time is passed in, never slept."""

import datetime as dt

from app.auth import sessions, users
from app.db import SessionRow, UserRow, session_scope

T0 = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.UTC)


def make_user(email: str = "ana@example.com") -> str:
    return users.create_user(email, password_hash=None).id


def test_a_new_session_resolves_to_its_user() -> None:
    user_id = make_user()
    token = sessions.create(user_id, now=T0)
    found = sessions.resolve(token, now=T0)
    assert found is not None
    assert found.user.id == user_id
    assert found.user.email == "ana@example.com"


def test_tokens_are_random_and_long() -> None:
    user_id = make_user()
    a, b = sessions.create(user_id, now=T0), sessions.create(user_id, now=T0)
    assert a != b
    assert len(a) >= 40


def test_an_unknown_or_empty_token_resolves_to_nothing() -> None:
    make_user()
    assert sessions.resolve("not-a-token", now=T0) is None
    assert sessions.resolve("", now=T0) is None


def test_the_database_never_holds_the_token_itself() -> None:
    token = sessions.create(make_user(), now=T0)
    assert sessions.token_hash(token) != token
    assert sessions.resolve(sessions.token_hash(token), now=T0) is None  # the hash isn't a key


def test_a_session_expires_30_days_after_its_last_use() -> None:
    token = sessions.create(make_user(), now=T0)
    assert sessions.resolve(token, now=T0 + dt.timedelta(days=30) - dt.timedelta(seconds=1))
    later = sessions.create(make_user("bo@example.com"), now=T0)
    assert sessions.resolve(later, now=T0 + dt.timedelta(days=30, seconds=1)) is None
    # Expired is gone for good, even if the clock were to go back.
    assert sessions.resolve(later, now=T0) is None


def test_use_rolls_the_expiry_forward() -> None:
    token = sessions.create(make_user(), now=T0)
    day29 = T0 + dt.timedelta(days=29)
    found = sessions.resolve(token, now=day29)
    assert found is not None and found.rolled
    # 30 days after the last use, not after creation.
    assert sessions.resolve(token, now=day29 + dt.timedelta(days=29))


def test_use_within_a_minute_does_not_write() -> None:
    token = sessions.create(make_user(), now=T0)
    first = sessions.resolve(token, now=T0 + dt.timedelta(seconds=30))
    assert first is not None and not first.rolled
    second = sessions.resolve(token, now=T0 + dt.timedelta(seconds=61))
    assert second is not None and second.rolled


def test_delete_ends_the_session() -> None:
    token = sessions.create(make_user(), now=T0)
    sessions.delete(token)
    assert sessions.resolve(token, now=T0) is None
    sessions.delete(token)  # deleting again is fine


def test_a_disabled_users_session_stops_working() -> None:
    user_id = make_user()
    token = sessions.create(user_id, now=T0)
    with session_scope() as s:  # what `make disable-user` (#7) will do
        row = s.get(UserRow, user_id)
        assert row is not None
        row.disabled_at = T0
    assert sessions.resolve(token, now=T0) is None


def test_starting_a_session_clears_out_expired_ones() -> None:
    user_id = make_user()
    stale = sessions.create(user_id, now=T0)
    sessions.create(user_id, now=T0 + dt.timedelta(days=31))
    with session_scope() as s:
        assert s.get(SessionRow, sessions.token_hash(stale)) is None
