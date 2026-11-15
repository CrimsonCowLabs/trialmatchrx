"""Age and sex criteria come from the eligibility module's structured fields, never the LLM."""

import pytest

from app.pipeline.compile_criteria import parse_age_years, structured_criteria
from app.schemas import Criterion, Predicate


@pytest.mark.parametrize(
    ("raw", "years"),
    [
        ("18 Years", 18),
        ("75 years", 75),
        ("6 Months", 0.5),
        ("26 Weeks", 0.5),
        ("1 Year", 1),
        ("N/A", None),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_age_years(raw: str | None, years: float | None) -> None:
    assert parse_age_years(raw) == years


def test_min_max_age_and_female_only() -> None:
    criteria = structured_criteria(
        {"minimumAge": "18 Years", "maximumAge": "80 Years", "sex": "FEMALE"}
    )

    assert criteria == [
        Criterion(
            id="inc-age-min",
            type="inclusion",
            text="Minimum age: 18 Years",
            category="demographic",
            predicate=Predicate(field="age", op=">=", value=18, unit="years"),
            needs_judgment=False,
        ),
        Criterion(
            id="inc-age-max",
            type="inclusion",
            text="Maximum age: 80 Years",
            category="demographic",
            predicate=Predicate(field="age", op="<=", value=80, unit="years"),
            needs_judgment=False,
        ),
        Criterion(
            id="inc-sex",
            type="inclusion",
            text="Sex: FEMALE",
            category="demographic",
            predicate=Predicate(field="sex", op="==", value="female"),
            needs_judgment=False,
        ),
    ]


def test_male_only() -> None:
    (sex,) = structured_criteria({"sex": "MALE"})
    assert sex.predicate == Predicate(field="sex", op="==", value="male")


def test_all_sexes_and_no_age_limits_give_nothing() -> None:
    assert structured_criteria({"minimumAge": "N/A", "sex": "ALL"}) == []
    assert structured_criteria({}) == []


def test_unparseable_age_needs_judgment() -> None:
    (crit,) = structured_criteria({"minimumAge": "eighteen"})
    assert crit.id == "inc-age-min"
    assert crit.predicate is None
    assert crit.needs_judgment
