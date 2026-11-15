"""GET /api/trials/{nct}: served from the trials cache, traced, no network on a hit."""

import httpx

from app.schemas import TraceEvent, TrialDetail
from app.sources import ctgov
from tests.ctgov_fake import FakeCtgov, load
from tests.sse import client

STUDY = load("study.json")
NCT = STUDY["protocolSection"]["identificationModule"]["nctId"]


async def test_cached_trial_is_served_without_any_network_call() -> None:
    ctgov.cache_study(STUDY)
    # conftest's autouse transport raises on any ClinicalTrials.gov request.

    async with client() as c:
        resp = await c.get(f"/api/trials/{NCT}")
        trace = (await c.get(f"/api/runs/{resp.headers['x-run-id']}/trace")).json()

    assert resp.status_code == 200
    trial = TrialDetail.model_validate(resp.json())
    assert trial.nct_id == NCT
    assert trial.title.startswith("Combined Dose-Finding and CV Outcomes Study With CSL300")
    assert trial.overall_status == "RECRUITING"
    assert trial.phase == "PHASE2/PHASE3"
    assert trial.eligibility_text is not None
    assert trial.eligibility_text.startswith("Inclusion Criteria")
    assert trial.criteria == []
    events = [TraceEvent.model_validate(e) for e in trace]
    assert [(e.name, e.cache_hit) for e in events] == [("ctgov.cache_lookup", True)]


async def test_cache_miss_fetches_once_and_caches() -> None:
    fake = FakeCtgov()
    fake.install()

    async with client() as c:
        first = await c.get(f"/api/trials/{NCT}")
        second = await c.get(f"/api/trials/{NCT}")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(fake.requests) == 1


async def test_unknown_trial_is_404() -> None:
    FakeCtgov().install()

    async with client() as c:
        resp = await c.get("/api/trials/NCT00000000")

    assert resp.status_code == 404


async def test_upstream_failure_is_502() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    ctgov.set_transport(httpx.MockTransport(down))

    async with client() as c:
        resp = await c.get(f"/api/trials/{NCT}")

    assert resp.status_code == 502
