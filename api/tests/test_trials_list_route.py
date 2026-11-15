"""GET /api/trials: the trials cache as a list, read-only and offline."""

import copy
from typing import Any

from pydantic import TypeAdapter

from app.pipeline import criteria_cache
from app.schemas import Criterion, TrialListItem
from app.sources import ctgov
from tests.ctgov_fake import load
from tests.sse import client

STUDIES: list[dict[str, Any]] = load("search_page1.json")["studies"]
ITEMS = TypeAdapter(list[TrialListItem])

CRITERIA = [
    Criterion(
        id="inc-1",
        type="inclusion",
        text="Age 18 or older",
        category="demographic",
        predicate=None,
        needs_judgment=False,
    ),
    Criterion(
        id="exc-1",
        type="exclusion",
        text="Pregnant",
        category="other",
        predicate=None,
        needs_judgment=True,
    ),
]


def _newer_version(study: dict[str, Any], title: str) -> dict[str, Any]:
    newer = copy.deepcopy(study)
    proto = newer["protocolSection"]
    proto["statusModule"]["lastUpdatePostDateStruct"]["date"] = "2099-01-01"
    proto["identificationModule"]["briefTitle"] = title
    return newer


async def _list(**params: str) -> list[TrialListItem]:
    async with client() as c:
        resp = await c.get("/api/trials", params=params)
    assert resp.status_code == 200
    return ITEMS.validate_python(resp.json())


async def test_empty_cache_lists_nothing() -> None:
    assert await _list() == []


async def test_lists_each_cached_trial_once_sorted_by_nct_id() -> None:
    for study in STUDIES:
        ctgov.cache_study(study)
    # conftest's autouse transport raises on any ClinicalTrials.gov request.

    items = await _list()

    assert [i.nct_id for i in items] == ["NCT04984226", "NCT05485961", "NCT07662135"]
    first = items[0]
    assert first.title == "Sodium Bicarbonate and Mitochondrial Energetics in Persons With CKD"
    assert first.overall_status == ctgov.summarize(STUDIES[1]).overall_status
    assert first.phase == ctgov.summarize(STUDIES[1]).phase
    assert not first.compiled and first.criteria_count == 0


async def test_newest_cached_version_wins() -> None:
    ctgov.cache_study(STUDIES[0])
    ctgov.cache_study(_newer_version(STUDIES[0], "Renamed upstream"))

    items = await _list()

    assert [(i.nct_id, i.title) for i in items] == [("NCT05485961", "Renamed upstream")]


async def test_compiled_trials_report_their_criteria_count() -> None:
    for study in STUDIES:
        ctgov.cache_study(study)
    criteria_cache.put("NCT05485961", "h", "v1", None, CRITERIA)

    items = {i.nct_id: i for i in await _list()}

    assert items["NCT05485961"].compiled and items["NCT05485961"].criteria_count == 2
    assert not items["NCT07662135"].compiled


async def test_q_filters_case_insensitively_on_title_and_nct_id() -> None:
    for study in STUDIES:
        ctgov.cache_study(study)

    assert [i.nct_id for i in await _list(q="bicarbonate")] == ["NCT04984226"]
    assert [i.nct_id for i in await _list(q="nct0766")] == ["NCT07662135"]
    assert await _list(q="no such trial") == []


async def test_listing_is_not_a_traced_run() -> None:
    ctgov.cache_study(STUDIES[0])

    async with client() as c:
        resp = await c.get("/api/trials")

    assert resp.status_code == 200
    assert "x-run-id" not in resp.headers
