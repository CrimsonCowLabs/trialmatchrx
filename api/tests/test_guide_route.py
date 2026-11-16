"""GET /api/guide: the first-time guide's pinned runs, read straight from guide_pins."""

from pydantic import TypeAdapter

from app.schemas import GuidePin, GuideStep
from app.trace import store
from tests.sse import client

PINS = TypeAdapter(list[GuidePin])


async def _guide() -> list[GuidePin]:
    async with client() as c:
        resp = await c.get("/api/guide")
    assert resp.status_code == 200
    return PINS.validate_python(resp.json())


async def test_no_pins_lists_nothing() -> None:
    assert await _guide() == []


async def test_pinned_match_run_exists() -> None:
    run_id = store.create_run("match", {})
    store.upsert_guide_pin("als", run_id, None)

    assert await _guide() == [GuidePin(step="als", run_id=run_id, nct_id=None, run_exists=True)]


async def test_pin_whose_run_is_gone_does_not_exist() -> None:
    store.upsert_guide_pin("ipf", "no-such-run", None)

    [pin] = await _guide()

    assert (pin.run_id, pin.run_exists) == ("no-such-run", False)


async def test_feasibility_pin_carries_only_a_trial() -> None:
    store.upsert_guide_pin("feasibility", None, "NCT04000001")

    assert await _guide() == [
        GuidePin(step="feasibility", run_id=None, nct_id="NCT04000001", run_exists=False)
    ]


async def test_pins_come_back_in_guide_step_order() -> None:
    run_id = store.create_run("match", {})
    store.upsert_guide_pin("feasibility", None, "NCT04000001")
    shuffled: list[GuideStep] = ["pah", "als", "ipf_flip", "ipf"]
    for step in shuffled:
        store.upsert_guide_pin(step, run_id, None)

    assert [p.step for p in await _guide()] == ["als", "ipf", "ipf_flip", "pah", "feasibility"]


async def test_upsert_replaces_an_existing_pin() -> None:
    before = store.create_run("match", {})
    after = store.create_run("match", {})
    store.upsert_guide_pin("ipf", before, "NCT04000001")
    store.upsert_guide_pin("ipf", after, None)

    assert await _guide() == [GuidePin(step="ipf", run_id=after, nct_id=None, run_exists=True)]


async def test_delete_removes_one_pin() -> None:
    run_id = store.create_run("match", {})
    store.upsert_guide_pin("als", run_id, None)
    store.upsert_guide_pin("pah", run_id, None)

    assert store.delete_guide_pin("als") is True
    assert store.delete_guide_pin("als") is False

    assert [p.step for p in await _guide()] == ["pah"]
