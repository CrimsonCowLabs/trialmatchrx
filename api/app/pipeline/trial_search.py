"""Trial search for a match run: recruiting cached trials for the patient's condition, nearest
first.

    trials = await search_cached_trials(
        rec, (lat, lon), radius_mi=100, limit=20,
        condition="type 2 diabetes", patient_conditions=["chronic kidney disease"],
    )

The match never calls ClinicalTrials.gov: `make seed` fills the cache beforehand (SPEC.md
"seed_trials.py pre-fetches ... so the demo never depends on venue Wi-Fi").
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.pipeline.condition_match import condition_match, trial_terms
from app.sources import ctgov
from app.trace.recorder import TraceRecorder

EARTH_RADIUS_MI = 3958.8


@dataclass(frozen=True)
class CandidateTrial:
    nct_id: str
    title: str
    phase: str | None
    distance_mi: float | None  # to the nearest site; None when no site has coordinates
    study: dict[str, Any]  # raw v2 study JSON, for the compiler


def haversine_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(h))


def sites_by_distance(
    study: dict[str, Any], origin: tuple[float, float]
) -> list[tuple[float, dict[str, Any]]]:
    """(miles from `origin`, raw location) for every site with coordinates, nearest first."""
    locations = study["protocolSection"].get("contactsLocationsModule", {}).get("locations", [])
    sites = [
        (haversine_mi(origin, (geo["lat"], geo["lon"])), loc)
        for loc in locations
        if (geo := loc.get("geoPoint")) and "lat" in geo and "lon" in geo
    ]
    return sorted(sites, key=lambda site: site[0])


def nearest_site_mi(study: dict[str, Any], origin: tuple[float, float]) -> float | None:
    sites = sites_by_distance(study, origin)
    return round(sites[0][0], 1) if sites else None


def _candidate(study: dict[str, Any], origin: tuple[float, float]) -> CandidateTrial:
    summary = ctgov.summarize(study)
    return CandidateTrial(
        nct_id=summary.nct_id,
        title=summary.title,
        phase=summary.phase,
        distance_mi=nearest_site_mi(study, origin),
        study=study,
    )


def _sort_key(t: CandidateTrial) -> tuple[bool, float, str]:
    return (t.distance_mi is None, t.distance_mi or 0.0, t.nct_id)


# Condition-match tiers, best first: the requested condition, another of the patient's
# conditions, then a cached row with no conditions module (can't be ruled out yet).
TIER_REQUESTED, TIER_PATIENT, TIER_UNKNOWN = 0, 1, 2


async def filter_by_condition(
    rec: TraceRecorder,
    trials: list[CandidateTrial],
    condition: str | None,
    patient_conditions: Sequence[str],
) -> list[tuple[int, CandidateTrial]]:
    """Keep trials whose conditions / keywords match the requested condition or one of the
    patient's, tagged with their tier. A traced `condition_match` rule step.

    With no condition at all, nothing is filtered (every trial is TIER_REQUESTED).
    """
    requested = [condition] if condition and condition.strip() else []
    others = [c for c in patient_conditions if c.strip() and c not in requested]
    rule_input = {"condition": condition, "patient_conditions": others, "trials": len(trials)}
    async with rec.step("condition_match", "rule", rule_input) as s:
        kept: list[tuple[int, CandidateTrial]] = []
        matched: list[dict[str, str]] = []
        unknown: list[str] = []
        dropped: list[str] = []
        for t in trials:
            if not requested and not others:
                kept.append((TIER_REQUESTED, t))
            elif trial_terms(t.study) is None:
                kept.append((TIER_UNKNOWN, t))
                unknown.append(t.nct_id)
            elif m := condition_match(requested, t.study):
                kept.append((TIER_REQUESTED, t))
                matched.append({"nct": t.nct_id, "patient": m.patient_term, "trial": m.trial_term})
            elif m := condition_match(others, t.study):
                kept.append((TIER_PATIENT, t))
                matched.append({"nct": t.nct_id, "patient": m.patient_term, "trial": m.trial_term})
            else:
                dropped.append(t.nct_id)
        s.output = {"matched": matched, "no_conditions": unknown, "dropped": dropped}
        s.note = (
            f"{len(matched)} of {len(trials)} trials match the patient's conditions, "
            f"{len(dropped)} dropped"
            + (f", {len(unknown)} kept with no conditions cached" if unknown else "")
        )
    return kept


async def search_cached_trials(
    rec: TraceRecorder,
    origin: tuple[float, float],
    *,
    radius_mi: float,
    limit: int,
    condition: str | None = None,
    patient_conditions: Sequence[str] = (),
) -> list[CandidateTrial]:
    """Recruiting cached trials with a site within `radius_mi` of `origin` that study the
    requested `condition` or one of `patient_conditions`, at most `limit`. Requested-condition
    matches come first, then other-condition matches, then rows cached without conditions;
    nearest first within each. Traced as a `search_trials` tool step with a nested
    `condition_match` rule step.
    """
    tool_input = {
        "condition": condition,
        "patient_conditions": list(patient_conditions),
        "origin": list(origin),
        "radius_mi": radius_mi,
        "limit": limit,
    }
    async with rec.step("search_trials", "tool", tool_input) as s:
        cached = ctgov.cached_studies()
        recruiting = [
            st
            for st in cached
            if st["protocolSection"].get("statusModule", {}).get("overallStatus") == "RECRUITING"
        ]
        candidates = [_candidate(st, origin) for st in recruiting]
        # A trial with no site coordinates can't be ruled out by distance; it is kept and
        # ranked after every trial with a known distance.
        in_radius = [t for t in candidates if t.distance_mi is None or t.distance_mi <= radius_mi]
        on_topic = await filter_by_condition(rec, in_radius, condition, patient_conditions)
        ranked = sorted(on_topic, key=lambda tt: (tt[0], *_sort_key(tt[1])))
        found = [t for _, t in ranked][:limit]
        s.output = {
            "cached": len(cached),
            "recruiting": len(recruiting),
            "in_radius": len(in_radius),
            "condition_match": len(on_topic),
            "nct_ids": [t.nct_id for t in found],
        }
        s.note = (
            f"{len(found)} of {len(on_topic)} recruiting cached trials for the patient's "
            f"conditions within {radius_mi:g} mi"
        )
    return found
