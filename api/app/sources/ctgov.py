"""ClinicalTrials.gov API v2 client + SQLite cache of raw study JSON (SPEC.md "2. Trial search").

    study = await get_study("NCT05...", recorder=rec)   # cache first, fetch on a miss

Tests never hit the network: `set_transport()` swaps the transport every client is built with.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import distinct, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import col, select

from app.config import get_settings
from app.db import TrialCacheRow, session_scope, utcnow
from app.schemas import TrialDetail
from app.trace.recorder import TraceRecorder

BASE_URL = "https://clinicaltrials.gov/api/v2"
SACRAMENTO = (38.5816, -121.4944)
# The four modules SPEC.md names, plus `Phase` (designModule.phases) because TrialDetail and
# TrialMatch both carry `phase`. Everything else in designModule is left out.
FIELDS = "IdentificationModule,StatusModule,EligibilityModule,ContactsLocationsModule,Phase"
NCT_ID = re.compile(r"NCT\d{8}")
RETRIES = 5
RETRY_BACKOFF_S = 2.0  # doubles per attempt unless the API sends Retry-After
RETRY_MAX_WAIT_S = 30.0  # cap on any single wait, Retry-After included

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport `make_client()` uses (tests install a MockTransport)."""
    global _transport
    _transport = transport


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, transport=_transport, timeout=30.0)


async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> httpx.Response:
    """GET with a retry on 429 (the API rate-limits bursts, e.g. during `make seed`)."""
    for attempt in range(RETRIES):
        resp = await client.get(path, params=params)
        if resp.status_code != 429 or attempt == RETRIES - 1:
            return resp
        retry_after = resp.headers.get("Retry-After", "")
        delay = float(retry_after) if retry_after.isdigit() else RETRY_BACKOFF_S * 2**attempt
        await asyncio.sleep(min(delay, RETRY_MAX_WAIT_S))
    raise AssertionError("unreachable")


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
        page = (await _get(client, "/studies", params)).raise_for_status().json()
        studies.extend(page.get("studies", []))
        token = page.get("nextPageToken")
        if not token:
            return studies
        params = {**params, "pageToken": token}


async def fetch_study(nct: str, *, client: httpx.AsyncClient) -> dict[str, Any] | None:
    """One study by NCT ID from the API, or None if ClinicalTrials.gov doesn't know it."""
    resp = await _get(client, f"/studies/{nct}", {"fields": FIELDS})
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
    """Store a study under its key. Returns False if that exact version was already cached.

    INSERT OR IGNORE, so two concurrent misses for the same trial can't collide on the key.
    """
    nct, date = study_key(study)
    stmt = (
        sqlite_insert(TrialCacheRow)
        .values(nct_id=nct, last_update_post_date=date, fetched_at=utcnow(), data=study)
        .on_conflict_do_nothing()
    )
    with session_scope() as s:
        result = s.connection().execute(stmt)
        return bool(result.rowcount)


def cached_study(nct: str) -> dict[str, Any] | None:
    """The newest cached version of a study, without touching the network."""
    with session_scope() as s:
        row = s.exec(
            select(TrialCacheRow)
            .where(TrialCacheRow.nct_id == nct)
            .order_by(col(TrialCacheRow.last_update_post_date).desc())
        ).first()
        return None if row is None else row.data


def cached_studies() -> list[dict[str, Any]]:
    """The newest cached version of every study, without touching the network."""
    newest: dict[str, dict[str, Any]] = {}
    with session_scope() as s:
        rows = s.exec(
            select(TrialCacheRow).order_by(
                col(TrialCacheRow.nct_id), col(TrialCacheRow.last_update_post_date)
            )
        ).all()
        for row in rows:
            newest[row.nct_id] = row.data  # later (newer) versions overwrite older ones
    return list(newest.values())


def cached_count() -> int:
    """Distinct NCT IDs in the cache."""
    with session_scope() as s:
        count = s.exec(select(func.count(distinct(col(TrialCacheRow.nct_id))))).one()
        return int(count)


async def _fetch(nct: str) -> dict[str, Any] | None:
    async with make_client() as client:
        return await fetch_study(nct, client=client)


async def get_study(nct: str, *, recorder: TraceRecorder | None = None) -> dict[str, Any]:
    """Raw v2 study JSON for `nct` (case-insensitive): from the cache, else fetched once and
    cached.

    With a recorder, a hit is a `ctgov.cache_lookup` tool step (cache_hit=True) and a miss is a
    `ctgov.fetch_study` tool step. Raises StudyNotFoundError if the id is malformed (no network
    call) or the API has no such study.
    """
    nct = nct.strip().upper()
    if not NCT_ID.fullmatch(nct):
        raise StudyNotFoundError(nct)
    if recorder is None:
        study = cached_study(nct) or await _fetch(nct)
    else:
        study = cached_study(nct)
        if study is not None:
            async with recorder.step("ctgov.cache_lookup", "tool", {"nct": nct}) as s:
                s.output, s.cache_hit = _describe(study), True
                s.note = f"{nct} served from cache"
            return study
        async with recorder.step("ctgov.fetch_study", "tool", {"nct": nct}) as s:
            study = await _fetch(nct)
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
        criteria=[],  # the trials route fills this from the compile cache
    )


def _describe(study: dict[str, Any]) -> dict[str, Any]:
    nct, date = study_key(study)
    return {"nct": nct, "last_update_post_date": date}
