"""SQLite via SQLModel: one engine, a session helper, and the table definitions.

Add new tables here (trials cache, compiled criteria, cohort, eval_runs) as plain SQLModel
classes with `table=True`; `init_db()` creates whatever is missing at startup.
"""

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import JSON, Column, event
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine

from app.config import get_settings

_engine: Engine | None = None


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def get_engine() -> Engine:
    """The process-wide engine, created lazily from `Settings.database_url`."""
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def set_engine(engine: Engine) -> None:
    """Swap the process-wide engine (tests point it at a temp file)."""
    global _engine
    _engine = engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """`with session_scope() as s:` — commits on success, rolls back on error."""
    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_session() -> Iterator[Session]:
    """FastAPI dependency: `session: Session = Depends(get_session)`."""
    with session_scope() as session:
        yield session


# --------------------------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------------------------


class RunRow(SQLModel, table=True):
    """One match / closer / compile run. `result` holds the run's final JSON payload."""

    __tablename__ = "runs"

    id: str = Field(primary_key=True)
    kind: str = Field(index=True)  # RunKind
    status: str = "running"  # RunStatus
    created_at: dt.datetime = Field(default_factory=utcnow)
    ended_at: dt.datetime | None = None
    request: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None


class TraceEventRow(SQLModel, table=True):
    """Append-only log of every TraceEvent emission, keyed by (run_id, seq).

    A step is emitted twice under the same event id: once `started`, once with its final
    status. Replaying rows in seq order reproduces exactly what a live viewer saw.
    """

    __tablename__ = "trace_events"

    run_id: str = Field(primary_key=True, foreign_key="runs.id")
    seq: int = Field(primary_key=True)
    event_id: str = Field(index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class TrialCacheRow(SQLModel, table=True):
    """Raw ClinicalTrials.gov v2 study JSON, keyed by (NCT ID, lastUpdatePostDate).

    A re-fetch of a trial that changed upstream adds a new row; readers take the newest date.
    """

    __tablename__ = "trials_cache"

    nct_id: str = Field(primary_key=True)
    last_update_post_date: str = Field(primary_key=True)  # ISO "YYYY-MM-DD", sorts as text
    fetched_at: dt.datetime = Field(default_factory=utcnow)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
