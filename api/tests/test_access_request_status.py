"""SPEC.md "Admin", Request status: each access request is `pending`, `invited` (any invite made
for its email, `invites.create`) or `dismissed` (`access_requests.dismiss`), with when and by
whom; `access_requests.list_requests` orders them for the admin page; an older table gains the
columns."""

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect

from app import access_requests, db
from app.auth import invites, users
from app.db import AccessRequestRow, UserRow, as_utc, session_scope
from app.schemas import AccessRequestCreate
from scripts.access_requests import main as list_cli
from scripts.invite import main as invite_cli

T0 = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.UTC)
MINUTE = dt.timedelta(minutes=1)


@pytest.fixture(autouse=True)
def admins() -> None:
    """Accounts `admin-1` and `admin-2`: `handled_by` is a foreign key to users.id."""
    with session_scope() as s:
        for n in (1, 2):
            s.add(UserRow(id=f"admin-{n}", email=f"admin{n}@example.com", is_admin=True))


def request(email: str = "ana@acme.example", *, at: dt.datetime = T0, **fields: Any) -> int:
    """Store one request directly (no form, no throttle) and return its id."""
    with session_scope() as s:
        row = AccessRequestRow(
            name=fields.get("name", "Ana Silva"),
            email=email,
            organization="Acme",
            role="sponsor",
            ip="203.0.113.9",
            created_at=at,
        )
        s.add(row)
        s.flush()
        assert row.id is not None
        return row.id


def get(request_id: int) -> AccessRequestRow:
    with session_scope() as s:
        row = s.get(AccessRequestRow, request_id)
        assert row is not None
        s.expunge(row)
        return row


def test_a_new_request_is_pending() -> None:
    body = AccessRequestCreate.model_validate(
        {"name": "Ana", "email": "ana@acme.example", "organization": "Acme", "role": "cro"}
    )
    assert access_requests.submit(body, "203.0.113.9", now=T0) == "stored"
    [row] = access_requests.list_requests()
    assert (row.status, row.handled_at, row.handled_by) == ("pending", None, None)


# ---- An invite marks the email's pending requests invited ---------------------------------


def test_an_invite_marks_that_emails_pending_requests_invited() -> None:
    first = request("ana@acme.example")
    again = request("  Ana@ACME.example ", at=T0 + MINUTE)  # stored as typed
    other = request("bo@acme.example")
    invites.create("ana@acme.example", handled_by="admin-1", now=T0 + 2 * MINUTE)

    for rid in (first, again):
        row = get(rid)
        assert (row.status, row.handled_by) == ("invited", "admin-1")
        assert row.handled_at is not None and as_utc(row.handled_at) == T0 + 2 * MINUTE
    assert get(other).status == "pending"


def test_the_cli_invite_marks_requests_invited_with_no_admin(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rid = request("ana@acme.example")
    assert invite_cli(["ANA@acme.example"]) == 0
    row = get(rid)
    assert (row.status, row.handled_by) == ("invited", None)
    assert row.handled_at is not None
    capsys.readouterr()

    assert list_cli([]) == 0
    assert capsys.readouterr().out.splitlines()[1].split()[-1] == "invited"


def test_an_invite_leaves_handled_requests_alone() -> None:
    dismissed = request("ana@acme.example")
    invited = request("ana@acme.example", at=T0 + MINUTE)
    assert access_requests.dismiss(dismissed, "admin-1", now=T0)
    invites.create("ana@acme.example", now=T0 + MINUTE)
    first_invited_at = get(invited).handled_at

    invites.create("ana@acme.example", handled_by=None, now=T0 + 5 * MINUTE)

    assert (get(dismissed).status, get(dismissed).handled_by) == ("dismissed", "admin-1")
    assert get(invited).handled_at == first_invited_at  # a re-invite doesn't restamp it


def test_a_refused_invite_changes_no_request() -> None:
    users.create_user("ana@acme.example", password_hash=None)
    rid = request("ana@acme.example")
    with pytest.raises(invites.AlreadyHasAccount):
        invites.create("ana@acme.example")
    assert get(rid).status == "pending"


# ---- Dismiss ------------------------------------------------------------------------------


def test_dismiss_marks_a_pending_request_dismissed() -> None:
    rid = request()
    other = request(at=T0 + MINUTE)
    assert access_requests.dismiss(rid, "admin-1", now=T0 + 2 * MINUTE) is True
    row = get(rid)
    assert (row.status, row.handled_by) == ("dismissed", "admin-1")
    assert row.handled_at is not None and as_utc(row.handled_at) == T0 + 2 * MINUTE
    assert get(other).status == "pending"  # only that row, not the email's others


def test_dismiss_changes_only_a_pending_request() -> None:
    dismissed = request()
    assert access_requests.dismiss(dismissed, "admin-1", now=T0)
    assert access_requests.dismiss(dismissed, "admin-2", now=T0 + MINUTE) is False
    assert (get(dismissed).handled_by, as_utc(get(dismissed).handled_at or T0)) == (
        "admin-1",
        T0,
    )

    invited = request("bo@acme.example")
    invites.create("bo@acme.example")
    assert access_requests.dismiss(invited, "admin-1") is False
    assert get(invited).status == "invited"


def test_dismissing_an_unknown_request_changes_nothing() -> None:
    assert access_requests.dismiss(12345, "admin-1") is False


# ---- Listing ------------------------------------------------------------------------------


def test_lists_pending_first_then_newest_first() -> None:
    old_pending = request("a@x.example", at=T0)
    new_dismissed = request("b@x.example", at=T0 + 3 * MINUTE)
    new_pending = request("c@x.example", at=T0 + 2 * MINUTE)
    old_invited = request("d@x.example", at=T0 + MINUTE)
    tie = request("e@x.example", at=T0)  # same time as old_pending, later id
    access_requests.dismiss(new_dismissed, "admin-1")
    invites.create("d@x.example")

    order = [row.id for row in access_requests.list_requests()]

    assert order == [new_pending, tie, old_pending, new_dismissed, old_invited]


def test_listing_nothing_is_empty() -> None:
    assert access_requests.list_requests() == []


# ---- An older database --------------------------------------------------------------------


def _legacy_db(path: Path) -> None:
    """An `access_requests` table as it was before `status`, with a request in it."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE access_requests (id INTEGER NOT NULL PRIMARY KEY, name VARCHAR NOT NULL, "
        "email VARCHAR NOT NULL, organization VARCHAR NOT NULL, role VARCHAR NOT NULL, "
        "message VARCHAR, ip VARCHAR NOT NULL, created_at DATETIME NOT NULL)"
    )
    con.execute(
        "INSERT INTO access_requests VALUES (1, 'Old', 'old@x.example', 'Org', 'site', NULL, "
        "'203.0.113.1', '2026-11-01 00:00:00')"
    )
    con.commit()
    con.close()


def test_init_db_adds_the_status_columns_to_an_existing_table(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _legacy_db(path)
    db.set_engine(db.make_engine(f"sqlite:///{path}"))

    db.init_db()
    db.init_db()  # idempotent

    columns = {c["name"]: c for c in inspect(db.get_engine()).get_columns("access_requests")}
    assert {"status", "handled_at", "handled_by"} <= columns.keys()
    assert columns["status"]["nullable"] is False
    [old] = access_requests.list_requests()
    assert (old.status, old.handled_at, old.handled_by) == ("pending", None, None)
    assert access_requests.dismiss(1, users.create_user("a@b.c", password_hash=None).id)
