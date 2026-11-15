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


def with_conditions(study: dict[str, Any], conditions: list[str] | None) -> dict[str, Any]:
    """`study` with these conditions (no keywords), or with no conditions module at all."""
    proto = study["protocolSection"]
    proto.pop("conditionsModule", None)
    if conditions is not None:
        proto["conditionsModule"] = {"conditions": conditions}
    return study


def cache_at(nct: str, miles: float, conditions: list[str] | None) -> None:
    ctgov.cache_study(with_conditions(study_north_of_sacramento(nct, miles), conditions))


async def test_only_trials_for_the_patients_condition_are_kept() -> None:
    cache_at("NCT90000010", 10.0, ["ALS"])
    cache_at("NCT90000020", 20.0, ["Type 2 Diabetes"])
    cache_at("NCT90000030", 30.0, ["Amyotrophic Lateral Sclerosis"])
    rec = recorder()
    found = await search_cached_trials(
        rec, SACRAMENTO, radius_mi=100, limit=20, condition="amyotrophic lateral sclerosis"
    )
    assert [t.nct_id for t in found] == ["NCT90000010", "NCT90000030"]
    events = store.latest_events(rec.run_id)
    search = next(e for e in events if e.name == "search_trials")
    rule = next(e for e in events if e.name == "condition_match")
    assert rule.kind == "rule" and rule.parent_id == search.id
    assert rule.output is not None
    assert rule.output["dropped"] == ["NCT90000020"]
    assert rule.output["matched"] == [
        {"nct": "NCT90000010", "patient": "amyotrophic lateral sclerosis", "trial": "ALS"},
        {
            "nct": "NCT90000030",
            "patient": "amyotrophic lateral sclerosis",
            "trial": "Amyotrophic Lateral Sclerosis",
        },
    ]


async def test_requested_condition_then_other_conditions_then_rows_without_conditions() -> None:
    cache_at("NCT90000005", 5.0, None)  # cached before ConditionsModule: kept, ranked last
    cache_at("NCT90000015", 15.0, ["Hypertension"])
    cache_at("NCT90000025", 25.0, ["Diabetes Mellitus, Type 2"])
    cache_at("NCT90000035", 35.0, ["Chronic Kidney Disease"])
    rec = recorder()
    found = await search_cached_trials(
        rec,
        SACRAMENTO,
        radius_mi=100,
        limit=20,
        condition="type 2 diabetes",
        patient_conditions=["type 2 diabetes", "CKD stage 3a"],
    )
    assert [t.nct_id for t in found] == ["NCT90000025", "NCT90000035", "NCT90000005"]
    rule = next(e for e in store.latest_events(rec.run_id) if e.name == "condition_match")
    assert rule.output is not None
    assert rule.output["no_conditions"] == ["NCT90000005"]
    assert rule.output["dropped"] == ["NCT90000015"]
