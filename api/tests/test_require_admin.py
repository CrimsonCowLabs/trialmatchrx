"""SPEC.md "Admin": `users.is_admin`, `GET /api/auth/me` returning it, an older `users` table
gaining the column, and the `require_admin` dependency that will guard `/api/admin/*` (404 to
anyone but a signed-in admin). No admin route exists yet, so it's tried on a test-only app."""

import sqlite3
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from sqlalchemy import inspect

from app import db
from app.auth import sessions, users
from app.auth.deps import SESSION_COOKIE, require_admin, require_session
from app.db import UserRow, session_scope
from tests.test_auth_routes import PASSWORD, disable, https_client, login, make_user


def set_admin(user_id: str) -> None:
    with session_scope() as s:  # what `make admin` does
        row = s.get(UserRow, user_id)
        assert row is not None
        row.is_admin = True


def admin_app(*, gated: bool) -> FastAPI:
    """One admin-only route; `gated` also installs the app-wide session gate, as app.main does."""
    test_app = FastAPI(dependencies=[Depends(require_session)] if gated else [])

    @test_app.get("/api/admin/ping")
    def ping(user: Annotated[UserRow, Depends(require_admin)]) -> dict[str, str]:
        return {"email": user.email}

    return test_app


def client(test_app: FastAPI, token: str | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="https://test",
        cookies={SESSION_COOKIE: token} if token else None,
    )


async def ping(test_app: FastAPI, token: str | None = None) -> httpx.Response:
    async with client(test_app, token) as c:
        return await c.get("/api/admin/ping")


def test_a_new_account_is_not_an_admin() -> None:
    assert make_user().is_admin is False


async def test_me_says_whether_the_account_is_an_admin() -> None:
    user = make_user()
    async with https_client() as c:
        assert (await login(c, "ana@example.com", PASSWORD)).json()["is_admin"] is False
        assert (await c.get("/api/auth/me")).json()["is_admin"] is False
        set_admin(user.id)
        assert (await c.get("/api/auth/me")).json()["is_admin"] is True


async def test_an_admin_gets_through() -> None:
    user = make_user()
    set_admin(user.id)
    for gated in (False, True):
        r = await ping(admin_app(gated=gated), sessions.create(user.id))
        assert (r.status_code, r.json()) == (200, {"email": "ana@example.com"})


async def test_a_signed_in_non_admin_gets_404() -> None:
    token = sessions.create(make_user().id)
    for gated in (False, True):
        r = await ping(admin_app(gated=gated), token)
        assert (r.status_code, r.json()) == (404, {"detail": "Not Found"})


async def test_no_session_or_an_unknown_one_gets_404() -> None:
    for token in (None, "not-a-session"):
        r = await ping(admin_app(gated=False), token)
        assert (r.status_code, r.json()) == (404, {"detail": "Not Found"})


async def test_the_404_looks_like_an_unknown_route() -> None:
    token = sessions.create(make_user().id)
    async with client(admin_app(gated=False), token) as c:
        unknown = await c.get("/api/admin/nothing-here")
        guarded = await c.get("/api/admin/ping")
    assert (guarded.status_code, guarded.json()) == (unknown.status_code, unknown.json())


async def test_a_disabled_admin_gets_404() -> None:
    user = make_user()
    set_admin(user.id)
    token = sessions.create(user.id)
    disable(user.id)
    r = await ping(admin_app(gated=False), token)
    assert (r.status_code, r.json()) == (404, {"detail": "Not Found"})


def _legacy_users_db(path: Path) -> None:
    """A `users` table as it was before `is_admin`, with an account in it."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE users (id VARCHAR NOT NULL PRIMARY KEY, email VARCHAR NOT NULL UNIQUE, "
        "password_hash VARCHAR, created_at DATETIME NOT NULL, last_login_at DATETIME, "
        "disabled_at DATETIME)"
    )
    con.execute(
        "INSERT INTO users VALUES ('old', 'old@example.com', NULL, '2026-11-01', NULL, NULL)"
    )
    con.commit()
    con.close()


def test_init_db_adds_is_admin_to_an_existing_users_table(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _legacy_users_db(path)
    db.set_engine(db.make_engine(f"sqlite:///{path}"))

    db.init_db()
    db.init_db()  # idempotent: a restart doesn't add it twice

    [column] = [c for c in inspect(db.get_engine()).get_columns("users") if c["name"] == "is_admin"]
    assert column["nullable"] is False
    old = users.find_by_email("old@example.com")
    assert old is not None and old.is_admin is False  # the existing account got the default
    assert users.create_user("new@example.com", password_hash=None).is_admin is False
