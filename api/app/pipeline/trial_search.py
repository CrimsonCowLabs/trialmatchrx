"""Trial search for a match run: recruiting trials from the ctgov cache, nearest first.

    trials = await search_cached_trials(rec, (lat, lon), radius_mi=100, limit=20)

The match never calls ClinicalTrials.gov: `make seed` fills the cache beforehand (SPEC.md
"seed_trials.py pre-fetches ... so the demo never depends on venue Wi-Fi").
"""

import math
from dataclasses import dataclass
from typing import Any

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


async def search_cached_trials(
    rec: TraceRecorder,
    origin: tuple[float, float],
    *,
    radius_mi: float,
    limit: int,
    condition: str | None = None,
) -> list[CandidateTrial]:
    """Recruiting cached trials with a site within `radius_mi` of `origin`, nearest first,
    at most `limit`. Traced as a `search_trials` tool step.

    `condition` is recorded but not used to filter: the cache was seeded for T2D/CKD and the
    cached fields carry no conditions module to match against.
    """
    tool_input = {
        "condition": condition,
        "origin": list(origin),
        "radius_mi": radius_mi,
        "limit": limit,
    }
    async with rec.step("search_trials", "tool", tool_input) as s:
        # HACK(demo): `condition` doesn't filter; every recruiting cached trial is a candidate.
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
        found = sorted(in_radius, key=_sort_key)[:limit]
        s.output = {
            "cached": len(cached),
            "recruiting": len(recruiting),
            "in_radius": len(in_radius),
            "nct_ids": [t.nct_id for t in found],
        }
        s.note = (
            f"{len(found)} of {len(in_radius)} recruiting cached trials within {radius_mi:g} mi"
        )
    return found
