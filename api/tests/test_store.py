import datetime as dt

from app.schemas import TraceEvent, TraceStatus
from app.trace import store


def make_event(run_id: str, seq: int, event_id: str, status: TraceStatus = "ok") -> TraceEvent:
    return TraceEvent(
        id=event_id,
        run_id=run_id,
        parent_id=None,
        seq=seq,
        kind="step",
        name=f"step-{event_id}",
        status=status,
        started_at=dt.datetime(2026, 11, 11, 12, 0, tzinfo=dt.UTC),
        ended_at=None,
        input={"a": 1},
        output=None,
        model=None,
        tokens_in=None,
        tokens_out=None,
        cost_usd=None,
        note=None,
    )


def test_saved_events_load_back_in_seq_order() -> None:
    run_id = store.create_run("match", {"note": "x"})
    store.save_event(make_event(run_id, 2, "b"))
    store.save_event(make_event(run_id, 1, "a"))

    loaded = store.load_events(run_id)

    assert [e.seq for e in loaded] == [1, 2]
    assert loaded[0] == make_event(run_id, 1, "a")


def test_load_events_after_seq_skips_already_seen() -> None:
    run_id = store.create_run("match", {})
    for seq in (1, 2, 3):
        store.save_event(make_event(run_id, seq, str(seq)))

    assert [e.seq for e in store.load_events(run_id, after_seq=2)] == [3]


def test_latest_events_collapses_each_event_to_its_final_state() -> None:
    run_id = store.create_run("match", {})
    store.save_event(make_event(run_id, 1, "a", status="started"))
    store.save_event(make_event(run_id, 2, "b"))
    store.save_event(make_event(run_id, 3, "a", status="ok"))

    latest = store.latest_events(run_id)

    assert [(e.id, e.status) for e in latest] == [("a", "ok"), ("b", "ok")]


def test_run_lifecycle() -> None:
    run_id = store.create_run("match", {"condition": "t2d"})
    run = store.get_run(run_id)
    assert run is not None and run.status == "running" and run.request == {"condition": "t2d"}

    store.finish_run(run_id, "done", result={"matches": []})

    run = store.get_run(run_id)
    assert run is not None
    assert run.status == "done" and run.result == {"matches": []} and run.ended_at is not None
    assert store.get_run("missing") is None
