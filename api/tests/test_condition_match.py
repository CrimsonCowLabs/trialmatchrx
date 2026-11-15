"""condition_match: patient conditions vs a trial's conditions / keywords, a rule with synonyms."""

from typing import Any

import pytest

from app.pipeline.condition_match import condition_match, trial_terms


def study(conditions: list[str], keywords: list[str] | None = None) -> dict[str, Any]:
    module: dict[str, Any] = {"conditions": conditions}
    if keywords is not None:
        module["keywords"] = keywords
    return {"protocolSection": {"conditionsModule": module}}


@pytest.mark.parametrize(
    ("patient", "trial"),
    [
        ("type 2 diabetes", "Diabetes Mellitus, Type 2"),  # word order
        ("Type 2 Diabetes", "Type 2 Diabetes Mellitus (T2DM)"),
        ("T2DM", "Type 2 Diabetes"),  # synonym
        ("chronic kidney disease", "Chronic Kidney Diseases"),  # plural
        ("chronic kidney disease stage 3a", "Chronic Kidney Disease"),  # names a group alias
        ("CKD", "Diabetic Nephropathy"),
        ("ALS", "Amyotrophic Lateral Sclerosis"),
        ("amyotrophic lateral sclerosis", "ALS"),
        ("ALS", "Lou Gehrig's Disease"),
        ("amyotrophic lateral sclerosis", "Motor Neuron Disease"),
        ("idiopathic pulmonary fibrosis", "IPF"),
        ("IPF", "Pulmonary Fibrosis"),
        ("idiopathic pulmonary fibrosis", "Interstitial Lung Disease"),
        ("PAH", "Pulmonary Arterial Hypertension"),
        ("pulmonary arterial hypertension", "Hypertension, Pulmonary"),
    ],
)
def test_matches(patient: str, trial: str) -> None:
    m = condition_match([patient], study([trial]))
    assert m is not None and m.patient_term == patient and m.trial_term == trial


@pytest.mark.parametrize(
    ("patient", "trial"),
    [
        ("pulmonary arterial hypertension", "Hypertension"),  # broader trial term is not enough
        ("type 2 diabetes", "Type 1 Diabetes"),
        ("idiopathic pulmonary fibrosis", "Cystic Fibrosis"),
        ("ALS", "Multiple Sclerosis"),
        ("chronic kidney disease", "Acute Kidney Injury"),
    ],
)
def test_does_not_match(patient: str, trial: str) -> None:
    assert condition_match([patient], study([trial])) is None


def test_keywords_count_and_the_matched_term_is_reported() -> None:
    m = condition_match(["ckd"], study(["Cardiovascular Risk"], ["chronic kidney disease"]))
    assert m is not None and m.trial_term == "chronic kidney disease"


def test_a_row_without_a_conditions_module_has_no_terms() -> None:
    assert trial_terms({"protocolSection": {}}) is None
    assert condition_match(["ALS"], {"protocolSection": {}}) is None
