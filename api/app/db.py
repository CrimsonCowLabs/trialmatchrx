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


def as_utc(value: dt.datetime) -> dt.datetime:
    """SQLite hands datetimes back naive; every stored one is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


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


class CompiledCriteriaRow(SQLModel, table=True):
    """One trial's compiled criteria, keyed by NCT id + hash of its eligibility fields.

    `criteria` is the full `list[Criterion]` JSON (age/sex included). A row only counts as a
    cache hit when `prompt_version` matches the current prompt.
    """

    __tablename__ = "compiled_criteria"

    nct_id: str = Field(primary_key=True)
    criteria_hash: str = Field(primary_key=True)
    prompt_version: str
    model: str | None = None
    created_at: dt.datetime = Field(default_factory=utcnow, index=True)
    criteria: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))


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


class EvalRunRow(SQLModel, table=True):
    """One scored pass over the fixed TREC sample (`make eval`): BM25 or the matcher.

    `git_sha` and `prompt_version` pin what produced the numbers, so the /eval history ties
    each score to a prompt change.
    """

    __tablename__ = "eval_runs"

    id: str = Field(primary_key=True)
    created_at: dt.datetime = Field(default_factory=utcnow, index=True)
    system: str = Field(index=True)  # EvalSystem
    git_sha: str | None = None
    prompt_version: str | None = None
    sample_size: int  # judged (topic, trial) pairs scored
    topics: int
    dropped: int  # sampled trials that never made it into the sample
    metrics: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))


class LlmCacheRow(SQLModel, table=True):
    """One cached LLM answer, keyed by a hash of the prompt and the model's settings
    (`app/eval/llm_cache.py`). The eval reads it so a re-run on the same sample replays the same
    answers instead of asking the model again."""

    __tablename__ = "llm_cache"

    key: str = Field(primary_key=True)  # sha256 of (prompt, llm_string)
    created_at: dt.datetime = Field(default_factory=utcnow)
    generations: list[str] = Field(default_factory=list, sa_column=Column(JSON))  # lc dumps


class CohortPatientRow(SQLModel, table=True):
    """One synthetic patient of the feasibility cohort: `PatientFacts` JSON mapped from a
    Synthea FHIR bundle by `scripts/load_cohort.py`. Read into a DataFrame once per process."""

    __tablename__ = "cohort"

    id: str = Field(primary_key=True)  # the bundle's Patient id
    source: str  # bundle file name, so a row can be traced back to its record
    loaded_at: dt.datetime = Field(default_factory=utcnow)
    facts: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class GuidePinRow(SQLModel, table=True):
    """One step of the first-time guide, pinned to a recorded run (and, for `feasibility`,
    a trial). Written by `make guide-pin`; the API only reads it."""

    __tablename__ = "guide_pins"

    step: str = Field(primary_key=True)  # GuideStep
    run_id: str | None = None  # no foreign key: a pin outlives a deleted run (run_exists)
    nct_id: str | None = None
    pinned_at: dt.datetime = Field(default_factory=utcnow)


class UserRow(SQLModel, table=True):
    """One account (SPEC.md "Marketing and accounts"). `email` is stored normalized (trimmed,
    lowercased; `app/auth/users.normalize_email`). `password_hash` is null for a passkey-only
    account. A disabled account keeps its row (so a run's `created_by` still resolves) but
    can't sign in, and its sessions stop working."""

    __tablename__ = "users"

    id: str = Field(primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str | None = None  # Argon2id, argon2-cffi's PHC string
    created_at: dt.datetime = Field(default_factory=utcnow)
    last_login_at: dt.datetime | None = None
    disabled_at: dt.datetime | None = None


class SessionRow(SQLModel, table=True):
    """One signed-in browser. The cookie carries an opaque random token; only its SHA-256 is
    stored, so a copy of the database can't be replayed as cookies. A session lasts 30 days
    from `last_used_at`, which moves forward at most once a minute (`app/auth/sessions.py`)."""

    __tablename__ = "sessions"

    token_hash: str = Field(primary_key=True)  # sha256 hex of the cookie value
    user_id: str = Field(foreign_key="users.id", index=True)
    created_at: dt.datetime = Field(default_factory=utcnow)
    last_used_at: dt.datetime = Field(default_factory=utcnow)


class LoginFailureRow(SQLModel, table=True):
    """One failed sign-in, for the throttle (5 per email or per IP in 15 minutes,
    `app/auth/throttle.py`). Rows older than the window are pruned as new ones are added."""

    __tablename__ = "login_failures"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True)  # normalized, whether or not an account has it
    ip: str = Field(index=True)
    failed_at: dt.datetime = Field(default_factory=utcnow, index=True)


class InviteRow(SQLModel, table=True):
    """One invite link (SPEC.md "Marketing and accounts", Accounts). The link carries an opaque
    random token; only its SHA-256 is stored, like a session. It works once, until
    `expires_at` (7 days, `app/auth/invites.py`); accepting it creates the account and stamps
    `used_at`. `email` is normalized; inviting an email again adds another row."""

    __tablename__ = "invites"

    token_hash: str = Field(primary_key=True)  # sha256 hex of the token in the link
    email: str = Field(index=True)
    created_at: dt.datetime = Field(default_factory=utcnow)
    expires_at: dt.datetime
    used_at: dt.datetime | None = None
