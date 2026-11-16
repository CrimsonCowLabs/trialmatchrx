"""SPEC.md "Who started a run": new runs record a nullable `created_by` user id; old runs keep
null; every signed-in user still sees every run. Plus the column's arrival on a database made
before it existed (prod's `runs` table is populated)."""

import sqlite3
from pathlib import Path

import httpx
from sqlalchemy import inspect

from app import db
from app.auth import sessions, users
from app.auth.deps import SESSION_COOKIE
from app.db import RunRow, session_scope
from app.main import app
from app.sources import ctgov
from app.trace import store
from tests.ctgov_fake import load
from tests.sse import client, signed_in_user_id
from tests.test_routes import MATCH_BODY

STUDY = load("study.json")
NCT = STUDY["protocolSection"]["identificationModule"]["nctId"]


def other_client() -> httpx.AsyncClient:
    """Signed in as a second account."""
    other = users.create_user("other@example.com", password_hash=None)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
        cookies={SESSION_COOKIE: sessions.create(other.id)},
    )


def created_by(run_id: str) -> str | None:
    with session_scope() as s:
        run = s.get(RunRow, run_id)
        assert run is not None
        return run.created_by


async def test_a_match_run_records_who_started_it_and_everyone_sees_it() -> None:
    old = store.create_run("match", {})  # e.g. a run from before accounts, or a script's
    async with client() as c:
        run_id = (await c.post("/api/match", json=MATCH_BODY)).json()["run_id"]
        await c.get(f"/api/runs/{run_id}/events")  # wait for it to finish
    assert created_by(run_id) == signed_in_user_id()
    assert created_by(old) is None

    async with other_client() as c:
        listed = {r["run_id"] for r in (await c.get("/api/runs")).json()}
        assert (await c.get(f"/api/runs/{run_id}")).status_code == 200
    assert {run_id, old} <= listed


async def test_a_trial_run_records_who_started_it() -> None:
    ctgov.cache_study(STUDY)
    async with client() as c:
        run_id = (await c.get(f"/api/trials/{NCT}")).headers["x-run-id"]
    assert created_by(run_id) == signed_in_user_id()


def _legacy_db(path: Path) -> None:
    """A `runs` table as it was before `created_by`, with a run in it."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE runs (id VARCHAR NOT NULL PRIMARY KEY, kind VARCHAR NOT NULL, "
        "status VARCHAR NOT NULL, created_at DATETIME NOT NULL, ended_at DATETIME, "
        "request JSON, result JSON, error VARCHAR)"
    )
    con.execute(
        "INSERT INTO runs VALUES ('old-run', 'match', 'done', '2026-11-01 00:00:00', NULL, "
        "'{}', NULL, NULL)"
    )
    con.commit()
    con.close()


def test_init_db_adds_created_by_to_an_existing_runs_table(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _legacy_db(path)
    db.set_engine(db.make_engine(f"sqlite:///{path}"))

    db.init_db()
    db.init_db()  # idempotent: a restart doesn't add it twice

    columns = {c["name"] for c in inspect(db.get_engine()).get_columns("runs")}
    assert "created_by" in columns
    indexes = {i["name"] for i in inspect(db.get_engine()).get_indexes("runs")}
    assert "ix_runs_created_by" in indexes
    assert created_by("old-run") is None  # the old run is untouched
    new = store.create_run(
        "match", {}, created_by=users.create_user("a@b.c", password_hash=None).id
    )
    assert created_by(new) is not None
