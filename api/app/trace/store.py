"""SQLite persistence for runs and their trace events.

Writes are synchronous and tiny; they run on the event loop so that persist -> publish happens
in seq order without interleaving.
"""

import uuid
from typing import Any, cast, get_args

from sqlalchemy import ColumnClause, literal_column
from sqlmodel import col, select

from app.db import GuidePinRow, RunRow, TraceEventRow, session_scope, utcnow
from app.schemas import GuidePin, GuideStep, RunKind, RunStatus, TraceEvent


def create_run(kind: RunKind, request: dict[str, Any], *, created_by: str | None = None) -> str:
    """A new `running` run; `created_by` is the signed-in user who started it, if any."""
    run_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(RunRow(id=run_id, kind=kind, request=request, created_by=created_by))
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


_GUIDE_STEP_ORDER: dict[str, int] = {step: i for i, step in enumerate(get_args(GuideStep))}


def list_guide_pins() -> list[GuidePin]:
    """Every guide pin, in guide step order, with whether its run is still in the runs
    table. A row whose step isn't a `GuideStep` (a step since renamed or dropped) is left
    out."""
    with session_scope() as s:
        rows = [r for r in s.exec(select(GuidePinRow)).all() if r.step in _GUIDE_STEP_ORDER]
        run_ids = [r.run_id for r in rows if r.run_id is not None]
        existing = set(s.exec(select(RunRow.id).where(col(RunRow.id).in_(run_ids))).all())
        pins = [
            GuidePin(
                step=cast(GuideStep, r.step),
                run_id=r.run_id,
                nct_id=r.nct_id,
                run_exists=r.run_id in existing,
            )
            for r in rows
        ]
    return sorted(pins, key=lambda p: _GUIDE_STEP_ORDER[p.step])


def upsert_guide_pin(step: GuideStep, run_id: str | None, nct_id: str | None) -> None:
    """Pin a guide step, replacing any earlier pin for it (`make guide-pin`)."""
    with session_scope() as s:
        s.merge(GuidePinRow(step=step, run_id=run_id, nct_id=nct_id, pinned_at=utcnow()))


def delete_guide_pin(step: GuideStep) -> bool:
    """Unpin a guide step. False when it wasn't pinned."""
    with session_scope() as s:
        pin = s.get(GuidePinRow, step)
        if pin is None:
            return False
        s.delete(pin)
        return True


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
