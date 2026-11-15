"""rank: verdicts -> tier, and the order trials are shown in."""

from app.pipeline.rank import build_match, rank_matches, tier_for
from app.schemas import TrialMatch, Verdict


def verdicts(passes: int = 0, fails: int = 0, unknowns: int = 0) -> list[Verdict]:
    outcomes = ["pass"] * passes + ["fail"] * fails + ["unknown"] * unknowns
    return [
        Verdict(
            criterion_id=f"inc-{i}",
            outcome=o,  # type: ignore[arg-type]
            method="rule",
            criterion_quote="q",
            patient_evidence=None,
            rationale="r",
            verified=True,
            trace_event_id="e",
        )
        for i, o in enumerate(outcomes, 1)
    ]


def match(nct: str, distance: float | None, **counts: int) -> TrialMatch:
    return build_match(nct, f"Trial {nct}", None, distance, verdicts(**counts))


def test_tiers() -> None:
    assert tier_for(verdicts(passes=5)) == "likely"
    assert tier_for(verdicts(passes=5, unknowns=2)) == "likely"
    assert tier_for(verdicts(passes=5, unknowns=3)) == "needs_info"
    assert tier_for(verdicts(passes=5, fails=1)) == "ineligible"
    assert tier_for(verdicts(fails=1, unknowns=9)) == "ineligible"
    assert tier_for([]) == "likely"


def test_build_match_counts_every_outcome() -> None:
    m = match("NCT1", 3.0, passes=2, unknowns=1)
    assert m.counts == {"pass": 2, "fail": 0, "unknown": 1}
    assert m.tier == "likely"
    assert m.distance_mi == 3.0


def test_rank_by_tier_then_fewer_unknowns_then_distance() -> None:
    ranked = rank_matches(
        [
            match("ineligible-near", 1.0, fails=1),
            match("needs-info", 2.0, unknowns=5),
            match("likely-2-unknowns", 1.0, unknowns=2),
            match("likely-far", 40.0, passes=3),
            match("likely-near", 5.0, passes=3),
            match("likely-no-distance", None, passes=3),
        ]
    )
    assert [m.nct_id for m in ranked] == [
        "likely-near",
        "likely-far",
        "likely-no-distance",
        "likely-2-unknowns",
        "needs-info",
        "ineligible-near",
    ]
