"""search_cached_trials: recruiting trials from the ctgov cache within a radius, nearest first."""

import copy
import math
from typing import Any

from app.pipeline.study_source import fixture_nct_ids, load_fixture_study
from app.pipeline.trial_search import EARTH_RADIUS_MI, search_cached_trials
from app.sources import ctgov
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

SACRAMENTO = ctgov.SACRAMENTO


def recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("match", {}), EventBus())


def cache_all_fixtures() -> None:
    for nct in fixture_nct_ids():
        ctgov.cache_study(load_fixture_study(nct))


def study_north_of_sacramento(nct: str, miles: float) -> dict[str, Any]:
    """A recruiting fixture study renamed `nct`, with one site `miles` due north of Sacramento
    (along a meridian, so the haversine distance is exactly `miles`)."""
    study = copy.deepcopy(load_fixture_study("NCT07662135"))
    proto = study["protocolSection"]
    proto["identificationModule"]["nctId"] = nct
    lat = SACRAMENTO[0] + math.degrees(miles / EARTH_RADIUS_MI)
    proto["contactsLocationsModule"]["locations"] = [
        {"city": "Synthetic", "geoPoint": {"lat": lat, "lon": SACRAMENTO[1]}}
    ]
    return study


async def test_within_radius_nearest_first_with_distance() -> None:
    cache_all_fixtures()
    rec = recorder()
    found = await search_cached_trials(rec, SACRAMENTO, radius_mi=400, limit=20)

    # NCT07662135 has a Sacramento site; NCT07271186 ~132 mi; NCT07783802 ~368 mi.
    assert [t.nct_id for t in found] == ["NCT07662135", "NCT07271186", "NCT07783802"]
    assert found[0].distance_mi is not None and found[0].distance_mi < 1
    assert found[1].distance_mi is not None and 120 < found[1].distance_mi < 140
    step = next(e for e in store.latest_events(rec.run_id) if e.name == "search_trials")
    assert step.kind == "tool" and step.status == "ok"
    assert step.output is not None and step.output["nct_ids"] == [t.nct_id for t in found]


async def test_limit_and_radius() -> None:
    cache_all_fixtures()
    near = await search_cached_trials(recorder(), SACRAMENTO, radius_mi=50, limit=20)
    assert [t.nct_id for t in near] == ["NCT07662135"]
    one = await search_cached_trials(recorder(), SACRAMENTO, radius_mi=400, limit=1)
    assert [t.nct_id for t in one] == ["NCT07662135"]


async def test_skips_trials_no_longer_recruiting() -> None:
    study = copy.deepcopy(load_fixture_study("NCT07662135"))
    study["protocolSection"]["statusModule"]["overallStatus"] = "COMPLETED"
    ctgov.cache_study(study)
    assert await search_cached_trials(recorder(), SACRAMENTO, radius_mi=50, limit=20) == []


async def test_a_site_at_exactly_the_radius_is_inside() -> None:
    ctgov.cache_study(study_north_of_sacramento("NCT90000500", 50.0))
    ctgov.cache_study(study_north_of_sacramento("NCT90000501", 50.1))
    found = await search_cached_trials(recorder(), SACRAMENTO, radius_mi=50, limit=20)
    assert [(t.nct_id, t.distance_mi) for t in found] == [("NCT90000500", 50.0)]


async def test_a_100_mile_search_reaches_past_50_but_not_past_100() -> None:
    cache_all_fixtures()  # ~0, ~132 and ~368 mi
    ctgov.cache_study(study_north_of_sacramento("NCT90000700", 70.0))
    ctgov.cache_study(study_north_of_sacramento("NCT90001000", 100.0))
    ctgov.cache_study(study_north_of_sacramento("NCT90001001", 100.1))
    rec = recorder()
    found = await search_cached_trials(rec, SACRAMENTO, radius_mi=100, limit=20)
    assert [(t.nct_id, t.distance_mi) for t in found][1:] == [
        ("NCT90000700", 70.0),
        ("NCT90001000", 100.0),
    ]
    assert found[0].nct_id == "NCT07662135"
    step = next(e for e in store.latest_events(rec.run_id) if e.name == "search_trials")
    assert step.input is not None and step.input["radius_mi"] == 100
