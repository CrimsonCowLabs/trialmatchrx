"""SQLite persistence for runs and their trace events.

Writes are synchronous and tiny; they run on the event loop so that persist -> publish happens
in seq order without interleaving.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnClause, literal_column
from sqlmodel import col, select

from app.db import RunRow, TraceEventRow, session_scope, utcnow
from app.schemas import RunKind, RunStatus, TraceEvent


def create_run(kind: RunKind, request: dict[str, Any]) -> str:
    run_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(RunRow(id=run_id, kind=kind, request=request))
    return run_id


def finish_run(
    run_id: str,
    status: RunStatus,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with session_scope() as s:
        run = s.get(RunRow, run_id)
        if run is None:
            raise KeyError(run_id)
        run.status = status
        run.ended_at = utcnow()
        run.result = result
        run.error = error
        s.add(run)


def get_run(run_id: str) -> RunRow | None:
    with session_scope() as s:
        run = s.get(RunRow, run_id)
        if run is not None:
            s.expunge(run)
        return run


def list_runs(kind: RunKind, limit: int, status: RunStatus | None = None) -> list[RunRow]:
    """Runs of one kind (and status, if given), newest first (insertion order breaks a
    created_at tie)."""
    rowid: ColumnClause[int] = literal_column(f"{RunRow.__tablename__}.rowid")
    query = select(RunRow).where(RunRow.kind == kind)
    if status is not None:
        query = query.where(RunRow.status == status)
    with session_scope() as s:
        rows = s.exec(
            query.order_by(col(RunRow.created_at).desc(), rowid.desc()).limit(limit)
        ).all()
        for row in rows:
            s.expunge(row)
        return list(rows)


def save_event(event: TraceEvent) -> None:
    with session_scope() as s:
        s.add(
            TraceEventRow(
                run_id=event.run_id,
                seq=event.seq,
                event_id=event.id,
                data=event.model_dump(mode="json"),
            )
        )


def load_events(run_id: str, after_seq: int = 0) -> list[TraceEvent]:
    """Every stored emission for a run with seq > after_seq, in seq order."""
    with session_scope() as s:
        rows = s.exec(
            select(TraceEventRow)
            .where(TraceEventRow.run_id == run_id, TraceEventRow.seq > after_seq)
            .order_by(col(TraceEventRow.seq))
        ).all()
        return [TraceEvent.model_validate(r.data) for r in rows]


def latest_events(run_id: str) -> list[TraceEvent]:
    """One entry per event id, in its final state, ordered by when the event first appeared."""
    latest: dict[str, TraceEvent] = {}
    for event in load_events(run_id):
        latest[event.id] = event  # dicts keep first-insertion order
    return list(latest.values())
