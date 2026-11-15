"""Tiering and ranking (SPEC.md pipeline 4).

Tier: likely = no fails and at most 2 unknowns; needs_info = no fails, more unknowns;
ineligible = any fail. Order: tier, then more confirmed (pass) criteria, then fewer unknowns, then
distance (unknown distance last). Confirmed count comes before unknowns because a short note leaves
most of a real trial's criteria unknown, so fewer unknowns alone ranks short registries first.
"""

from typing import Literal

from app.schemas import TrialMatch, Verdict

Tier = Literal["likely", "needs_info", "ineligible"]

MAX_UNKNOWNS_FOR_LIKELY = 2
TIER_ORDER: tuple[Tier, ...] = ("likely", "needs_info", "ineligible")


def count_outcomes(verdicts: list[Verdict]) -> dict[str, int]:
    counts = {"pass": 0, "fail": 0, "unknown": 0}
    for v in verdicts:
        counts[v.outcome] += 1
    return counts


def tier_for(verdicts: list[Verdict]) -> Tier:
    counts = count_outcomes(verdicts)
    if counts["fail"]:
        return "ineligible"
    return "likely" if counts["unknown"] <= MAX_UNKNOWNS_FOR_LIKELY else "needs_info"


def build_match(
    nct_id: str, title: str, phase: str | None, distance_mi: float | None, verdicts: list[Verdict]
) -> TrialMatch:
    return TrialMatch(
        nct_id=nct_id,
        title=title,
        phase=phase,
        distance_mi=distance_mi,
        tier=tier_for(verdicts),
        verdicts=verdicts,
        counts=count_outcomes(verdicts),
    )


def _sort_key(m: TrialMatch) -> tuple[int, int, int, bool, float, str]:
    distance = m.distance_mi
    return (
        TIER_ORDER.index(m.tier),
        -m.counts.get("pass", 0),
        m.counts.get("unknown", 0),
        distance is None,
        distance or 0.0,
        m.nct_id,  # stable tiebreak so reruns order identically
    )


def rank_matches(matches: list[TrialMatch]) -> list[TrialMatch]:
    return sorted(matches, key=_sort_key)
