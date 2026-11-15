"""ClinicalTrials.gov client + cache, on recorded responses (tests/fixtures/ctgov/), no network."""

import copy

import httpx
import pytest

from app.sources import ctgov
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder
from tests.ctgov_fake import FakeCtgov, load, nct_ids


async def test_search_follows_next_page_token_with_spec_params() -> None:
    fake = FakeCtgov()
    async with fake.client() as client:
        studies = await ctgov.search_studies("chronic kidney disease", client=client)

    assert nct_ids(studies) == nct_ids(load("search_page1.json")["studies"]) + nct_ids(
        load("search_page2.json")["studies"]
    )
    first, second = fake.requests
    assert first.url.params["query.cond"] == "chronic kidney disease"
    assert first.url.params["filter.overallStatus"] == "RECRUITING"
    assert first.url.params["filter.geo"] == "distance(38.5816,-121.4944,50mi)"
    assert first.url.params["pageSize"] == "50"
    assert "pageToken" not in first.url.params
    assert second.url.params["pageToken"] == load("search_page1.json")["nextPageToken"]


def new_recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("trial", {}), EventBus())


async def test_get_study_fetches_on_miss_then_serves_from_cache() -> None:
    fake = FakeCtgov()
    fake.install()
    study = load("study.json")
    nct = nct_ids([study])[0]
    rec = new_recorder()

    fetched = await ctgov.get_study(nct, recorder=rec)
    cached = await ctgov.get_study(nct, recorder=rec)

    assert fetched == study
    assert cached == study
    assert [r.url.path for r in fake.requests] == [f"/api/v2/studies/{nct}"]
    assert fake.requests[0].url.params["fields"] == ctgov.FIELDS
    events = store.latest_events(rec.run_id)
    assert [(e.kind, e.name, e.status, e.cache_hit) for e in events] == [
        ("tool", "ctgov.fetch_study", "ok", False),
        ("tool", "ctgov.cache_lookup", "ok", True),
    ]
    assert events[0].input == {"nct": nct}
    assert events[0].output == {"nct": nct, "last_update_post_date": "2026-09-21"}


async def test_get_study_unknown_nct_raises_not_found() -> None:
    fake = FakeCtgov()
    fake.install()

    with pytest.raises(ctgov.StudyNotFoundError):
        await ctgov.get_study("NCT00000000")


async def test_get_study_ids_are_case_insensitive_and_malformed_ids_never_hit_the_network() -> None:
    study = load("study.json")
    ctgov.cache_study(study)
    nct = nct_ids([study])[0]

    assert await ctgov.get_study(f" {nct.lower()} ") == study
    with pytest.raises(ctgov.StudyNotFoundError):
        await ctgov.get_study("not-an-nct")  # conftest's transport raises on any request


async def test_cache_serves_the_newest_version_of_a_study() -> None:
    old = load("study.json")
    new = copy.deepcopy(old)
    new["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"] = "2026-10-30"
    nct = nct_ids([old])[0]

    assert ctgov.cache_study(new) is True
    assert ctgov.cache_study(old) is True
    assert ctgov.cache_study(old) is False  # same (nct, date) twice is a no-op

    assert ctgov.cached_study(nct) == new
    assert ctgov.cached_count() == 1


async def test_seed_caches_every_condition_and_dedupes() -> None:
    fake = FakeCtgov()
    async with fake.client() as client:
        stats = await ctgov.seed_cache(
            ["type 2 diabetes", "chronic kidney disease"], client=client, radius_mi=100
        )

    unique = set(
        nct_ids(load("search_page1.json")["studies"] + load("search_page2.json")["studies"])
    )
    # The fake answers every condition with the same two pages: 12 seen, 6 distinct.
    assert stats == ctgov.SeedStats(seen=12, new=6, cached_total=len(unique))
    assert {r.url.params["query.cond"] for r in fake.requests} == {
        "type 2 diabetes",
        "chronic kidney disease",
    }
    assert {r.url.params["filter.geo"] for r in fake.requests} == {
        "distance(38.5816,-121.4944,100mi)"
    }
    assert all(ctgov.cached_study(n) is not None for n in unique)


async def test_rate_limited_requests_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ctgov, "RETRY_BACKOFF_S", 0.0)
    fake = FakeCtgov()
    calls = 0

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429) if calls <= 2 else fake(request)

    ctgov.set_transport(httpx.MockTransport(flaky))
    study = await ctgov.get_study(nct_ids([load("study.json")])[0])

    assert study == load("study.json")
    assert calls == 3


@pytest.mark.live
async def test_live_search_returns_recruiting_studies_with_cache_keys() -> None:
    async with ctgov.make_client() as client:
        studies = await ctgov.search_studies("type 2 diabetes", client=client)

    assert studies
    for study in studies:
        ctgov.study_key(study)  # every study carries nctId + lastUpdatePostDate
        assert study["protocolSection"]["statusModule"]["overallStatus"] == "RECRUITING"
