"""ClinicalTrials.gov API v2 client + SQLite cache of raw study JSON (SPEC.md "2. Trial search").

    study = await get_study("NCT05...", recorder=rec)   # cache first, fetch on a miss

Tests never hit the network: `set_transport()` swaps the transport every client is built with.
"""

from dataclasses import dataclass
from typing import Any

import httpx
from sqlmodel import col, select

from app.config import get_settings
from app.db import TrialCacheRow, session_scope
from app.schemas import TrialDetail
from app.trace.recorder import TraceRecorder

BASE_URL = "https://clinicaltrials.gov/api/v2"
SACRAMENTO = (38.5816, -121.4944)
# The four modules SPEC.md names, plus `Phase` (designModule.phases) because TrialDetail and
# TrialMatch both carry `phase`. Everything else in designModule is left out.
FIELDS = "IdentificationModule,StatusModule,EligibilityModule,ContactsLocationsModule,Phase"

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport `make_client()` uses (tests install a MockTransport)."""
    global _transport
    _transport = transport


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, transport=_transport, timeout=30.0)


def search_params(
    cond: str, *, radius_mi: float | None = None, page_size: int = 50
) -> dict[str, Any]:
    radius = get_settings().ctgov_radius_mi if radius_mi is None else radius_mi
    lat, lon = SACRAMENTO
    return {
        "query.cond": cond,
        "filter.overallStatus": "RECRUITING",
        "filter.geo": f"distance({lat},{lon},{radius:g}mi)",
        "pageSize": page_size,
        "fields": FIELDS,
    }


async def search_studies(
    cond: str, *, client: httpx.AsyncClient, radius_mi: float | None = None
) -> list[dict[str, Any]]:
    """Every recruiting study for `cond` near Sacramento, following `nextPageToken`."""
    params = search_params(cond, radius_mi=radius_mi)
    studies: list[dict[str, Any]] = []
    while True:
        page = (await client.get("/studies", params=params)).raise_for_status().json()
        studies.extend(page.get("studies", []))
        token = page.get("nextPageToken")
        if not token:
            return studies
        params = {**params, "pageToken": token}


async def fetch_study(nct: str, *, client: httpx.AsyncClient) -> dict[str, Any] | None:
    """One study by NCT ID from the API, or None if ClinicalTrials.gov doesn't know it."""
    resp = await client.get(f"/studies/{nct}", params={"fields": FIELDS})
    if resp.status_code == 404:
        return None
    study: dict[str, Any] = resp.raise_for_status().json()
    return study


# --------------------------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------------------------


class StudyNotFoundError(LookupError):
    """Neither the cache nor ClinicalTrials.gov has this NCT ID."""


def study_key(study: dict[str, Any]) -> tuple[str, str]:
    """(NCT ID, lastUpdatePostDate): the cache key."""
    proto = study["protocolSection"]
    nct: str = proto["identificationModule"]["nctId"]
    date: str = proto["statusModule"]["lastUpdatePostDateStruct"]["date"]
    return nct, date


def cache_study(study: dict[str, Any]) -> bool:
    """Store a study under its key. Returns False if that exact version was already cached."""
    nct, date = study_key(study)
    with session_scope() as s:
        if s.get(TrialCacheRow, (nct, date)) is not None:
            return False
        s.add(TrialCacheRow(nct_id=nct, last_update_post_date=date, data=study))
        return True


def cached_study(nct: str) -> dict[str, Any] | None:
    """The newest cached version of a study, without touching the network."""
    with session_scope() as s:
        row = s.exec(
            select(TrialCacheRow)
            .where(TrialCacheRow.nct_id == nct)
            .order_by(col(TrialCacheRow.last_update_post_date).desc())
        ).first()
        return None if row is None else row.data


def cached_count() -> int:
    """Distinct NCT IDs in the cache."""
    with session_scope() as s:
        return len(set(s.exec(select(TrialCacheRow.nct_id)).all()))


async def get_study(
    nct: str,
    *,
    recorder: TraceRecorder | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Raw v2 study JSON for `nct`: from the cache, else fetched once and cached.

    With a recorder, a hit is a `ctgov.cache_lookup` tool event (cache_hit=True) and a miss is a
    `ctgov.fetch_study` tool step. Raises StudyNotFoundError if the API has no such study.
    """
    study = cached_study(nct)
    if study is not None:
        if recorder is not None:
            recorder.event(
                "ctgov.cache_lookup",
                "tool",
                input={"nct": nct},
                output=_describe(study),
                cache_hit=True,
                note=f"{nct} served from cache",
            )
        return study

    async def fetch() -> dict[str, Any] | None:
        if client is not None:
            return await fetch_study(nct, client=client)
        async with make_client() as own:
            return await fetch_study(nct, client=own)

    if recorder is None:
        study = await fetch()
    else:
        async with recorder.step("ctgov.fetch_study", "tool", {"nct": nct}) as s:
            study = await fetch()
            s.output = {"nct": nct, "found": False} if study is None else _describe(study)
            s.note = f"{nct} fetched from ClinicalTrials.gov (cache miss)"
    if study is None:
        raise StudyNotFoundError(nct)
    cache_study(study)
    return study


@dataclass(frozen=True)
class SeedStats:
    seen: int  # studies returned across every condition (with duplicates)
    new: int  # (nct, lastUpdatePostDate) versions added to the cache by this seed
    cached_total: int  # distinct NCT IDs in the cache afterwards


async def seed_cache(
    conditions: list[str], *, client: httpx.AsyncClient, radius_mi: float | None = None
) -> SeedStats:
    """Search each condition and cache every study found; overlapping results dedupe on key."""
    seen = new = 0
    for cond in conditions:
        for study in await search_studies(cond, client=client, radius_mi=radius_mi):
            seen += 1
            new += cache_study(study)
    return SeedStats(seen=seen, new=new, cached_total=cached_count())


def summarize(study: dict[str, Any]) -> TrialDetail:
    """The `TrialDetail` view of a raw study. `criteria` is left empty for the compiler."""
    proto = study["protocolSection"]
    ident = proto.get("identificationModule", {})
    phases = proto.get("designModule", {}).get("phases") or []
    return TrialDetail(
        nct_id=ident["nctId"],
        title=ident.get("briefTitle") or ident.get("officialTitle") or ident["nctId"],
        phase="/".join(phases) or None,
        overall_status=proto.get("statusModule", {}).get("overallStatus"),
        eligibility_text=proto.get("eligibilityModule", {}).get("eligibilityCriteria"),
        criteria=[],
    )


def _describe(study: dict[str, Any]) -> dict[str, Any]:
    nct, date = study_key(study)
    return {"nct": nct, "last_update_post_date": date}
