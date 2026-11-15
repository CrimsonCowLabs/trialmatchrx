"""Compiled criteria are cached per NCT id + hash of the eligibility text (and prompt version)."""

from app.pipeline import criteria_cache as cache
from app.schemas import Criterion

ELIG = {
    "eligibilityCriteria": "Inclusion Criteria:\n\n* T2DM",
    "minimumAge": "18 Years",
    "sex": "ALL",
}
CRITERIA = [
    Criterion(
        id="inc-1",
        type="inclusion",
        text="T2DM",
        category="diagnosis",
        predicate=None,
        needs_judgment=True,
    )
]


def test_stored_criteria_come_back_for_the_same_text_and_prompt() -> None:
    key = cache.eligibility_hash(ELIG)
    cache.put("NCT1", key, "compile-v1", "claude-x", CRITERIA)

    assert cache.get("NCT1", key, "compile-v1") == CRITERIA


def test_changed_text_or_prompt_version_is_a_miss() -> None:
    key = cache.eligibility_hash(ELIG)
    cache.put("NCT1", key, "compile-v1", "claude-x", CRITERIA)

    edited = cache.eligibility_hash({**ELIG, "eligibilityCriteria": "Inclusion Criteria:\n* T1DM"})
    assert edited != key
    assert cache.get("NCT1", edited, "compile-v1") is None
    assert cache.get("NCT1", key, "compile-v2") is None
    assert cache.get("NCT2", key, "compile-v1") is None


def test_age_limits_are_part_of_the_hash() -> None:
    capped = {**ELIG, "maximumAge": "75 Years"}
    assert cache.eligibility_hash(ELIG) != cache.eligibility_hash(capped)


def test_put_replaces_and_latest_returns_the_newest() -> None:
    key = cache.eligibility_hash(ELIG)
    cache.put("NCT1", key, "compile-v1", "claude-x", [])
    cache.put("NCT1", key, "compile-v1", "claude-x", CRITERIA)

    assert cache.latest("NCT1") == CRITERIA
    assert cache.latest("NCT-never-compiled") == []
