"""GET /api/runs: past runs, newest first, read straight from the runs table."""

from typing import Any

from pydantic import TypeAdapter

from app.schemas import RunListItem, RunSummary, TierCounts
from app.sources import ctgov
from app.trace import store
from tests.ctgov_fake import load
from tests.sse import client

ITEMS = TypeAdapter(list[RunListItem])


def _patient(age: int | None, sex: str | None) -> dict[str, Any]:
    return {
        "age": age,
        "sex": sex,
        "conditions": [],
        "labs": {},
        "vitals": {},
        "meds": [],
        "pregnant": None,
        "smoker": None,
        "lat": None,
        "lon": None,
    }


def _match(nct: str, tier: str) -> dict[str, Any]:
    return {
        "nct_id": nct,
        "title": f"Trial {nct}",
        "phase": None,
        "distance_mi": None,
        "tier": tier,
        "verdicts": [],
        "counts": {"pass": 0, "fail": 0, "unknown": 0},
    }


async def _list(**params: str | int) -> list[RunListItem]:
    async with client() as c:
        resp = await c.get("/api/runs", params=params)
    assert resp.status_code == 200
    return ITEMS.validate_python(resp.json())


async def test_no_runs_lists_nothing() -> None:
    assert await _list() == []


async def test_lists_only_match_runs_by_default_newest_first() -> None:
    first = store.create_run("match", {})
    store.create_run("compile", {"nct": "NCT1"})
    store.create_run("closer", {})
    second = store.create_run("match", {})
    store.finish_run(second, "failed", error="boom")

    items = await _list()

    assert [(i.run_id, i.kind, i.status) for i in items] == [
        (second, "match", "failed"),
        (first, "match", "running"),
    ]
    assert items[0].ended_at is not None and items[1].ended_at is None


async def test_times_are_utc() -> None:
    run_id = store.create_run("match", {})
    store.finish_run(run_id, "done")

    async with client() as c:
        [raw] = (await c.get("/api/runs")).json()

    assert raw["created_at"].endswith(("Z", "+00:00"))
    assert raw["ended_at"].endswith(("Z", "+00:00"))


async def test_kind_filters_the_list() -> None:
    store.create_run("match", {})
    closer = store.create_run("closer", {})

    assert [i.run_id for i in await _list(kind="closer")] == [closer]


async def test_unknown_kind_is_422() -> None:
    async with client() as c:
        resp = await c.get("/api/runs", params={"kind": "nope"})
    assert resp.status_code == 422


async def test_limit_is_honoured_and_capped() -> None:
    ids = [store.create_run("match", {}) for _ in range(3)]

    assert [i.run_id for i in await _list(limit=2)] == [ids[2], ids[1]]
    async with client() as c:
        assert (await c.get("/api/runs", params={"limit": 201})).status_code == 422
        assert (await c.get("/api/runs", params={"limit": 0})).status_code == 422
        assert (await c.get("/api/runs", params={"limit": 200})).status_code == 200


async def test_finished_run_gets_a_patient_label_and_tier_counts() -> None:
    run_id = store.create_run("match", {})
    store.finish_run(
        run_id,
        "done",
        result={
            "patient": _patient(58, "female"),
            "matches": [
                _match("NCT1", "likely"),
                _match("NCT2", "needs_info"),
                _match("NCT3", "needs_info"),
                _match("NCT4", "ineligible"),
            ],
        },
    )

    [item] = await _list()

    assert item.patient_label == "58 F"
    assert item.tier_counts == TierCounts(likely=1, needs_info=2, ineligible=1)


async def test_patient_label_uses_what_was_parsed() -> None:
    for age, sex in [(None, "male"), (61, None), (None, None)]:
        run_id = store.create_run("match", {})
        store.finish_run(run_id, "done", result={"patient": _patient(age, sex), "matches": []})

    assert [i.patient_label for i in await _list()] == [None, "61", "M"]


async def test_running_run_has_no_label_and_zero_counts() -> None:
    store.create_run("match", {})

    [item] = await _list()

    assert item.status == "running"
    assert item.patient_label is None
    assert item.tier_counts == TierCounts()


async def test_run_detail_still_resolves_beside_the_list() -> None:
    run_id = store.create_run("match", {})

    async with client() as c:
        resp = await c.get(f"/api/runs/{run_id}")

    assert resp.status_code == 200
    assert RunSummary.model_validate(resp.json()).run_id == run_id


async def test_listing_creates_no_runs_or_trace_events() -> None:
    ctgov.cache_study(load("study.json"))
    run_id = store.create_run("match", {})

    async with client() as c:
        for path in ["/api/trials", "/api/runs", "/api/runs?kind=trial"]:
            assert (await c.get(path)).status_code == 200

    for kind in ["match", "closer", "compile", "trial"]:
        expected = [run_id] if kind == "match" else []
        assert [i.run_id for i in await _list(kind=kind)] == expected
    assert store.load_events(run_id) == []
