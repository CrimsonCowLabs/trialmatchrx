"""Does a trial study the patient's condition? A rule, no LLM.

    match = condition_match(["type 2 diabetes"], study)   # -> ConditionMatch | None

A patient term matches a trial term (one of `conditionsModule.conditions` / `.keywords`) when
every word of the patient term, or of one of its synonyms, appears in the trial term after
lowercasing, dropping punctuation and a plural "s". So "type 2 diabetes" matches "Diabetes
Mellitus, Type 2" (any word order), "chronic kidney disease" matches "Chronic Kidney Diseases",
and "ALS" matches "Amyotrophic Lateral Sclerosis" through the synonym table. Only the patient
side has to be covered: a trial term "Hypertension" does not match a patient with "pulmonary
arterial hypertension".
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Each group is one disease; a patient term that contains any alias stands for every alias.
# Kept small on purpose: the four demo conditions. Breadth is a judgement call per group.
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    (
        "amyotrophic lateral sclerosis",
        "als",
        "lou gehrig's disease",
        "motor neuron disease",
        "motor neurone disease",
    ),
    # Broad: IPF trials often enrol "progressive pulmonary fibrosis" or "interstitial lung
    # disease" as a whole, so an IPF patient is matched to all three.
    (
        "idiopathic pulmonary fibrosis",
        "ipf",
        "pulmonary fibrosis",
        "interstitial lung disease",
        "ild",
    ),
    # Broad: "pulmonary hypertension" (any WHO group) is kept for a PAH patient; plain
    # "hypertension" is not, it is a different disease.
    ("pulmonary arterial hypertension", "pah", "pulmonary hypertension"),
    (
        "type 2 diabetes",
        "t2d",
        "t2dm",
        "diabetes mellitus type 2",
        "type ii diabetes",
        "non insulin dependent diabetes",
    ),
    (
        "chronic kidney disease",
        "ckd",
        "diabetic kidney disease",
        "dkd",
        "diabetic nephropathy",
        "chronic renal insufficiency",
    ),
)


def words(text: str) -> frozenset[str]:
    """Lowercase words with apostrophes and punctuation gone and a plural "s" dropped."""
    text = re.sub(r"['’]", "", text.lower())
    return frozenset(
        w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", text)
    )


_GROUPS = tuple(tuple(words(alias) for alias in group) for group in SYNONYM_GROUPS)


def expand(term: str) -> list[frozenset[str]]:
    """The word sets that stand for `term`: itself, plus every alias of any group it names."""
    own = words(term)
    out = [own] if own else []
    for group in _GROUPS:
        if any(alias <= own for alias in group):
            out.extend(alias for alias in group if alias not in out)
    return out


def trial_terms(study: dict[str, Any]) -> list[str] | None:
    """The trial's conditions then keywords, or None when the cached row has no conditions
    module (cached before ctgov.FIELDS asked for it)."""
    module = study["protocolSection"].get("conditionsModule")
    if module is None:
        return None
    return [*module.get("conditions", []), *module.get("keywords", [])]


@dataclass(frozen=True)
class ConditionMatch:
    patient_term: str  # as the patient's condition was written
    trial_term: str  # the trial condition / keyword it matched, as ClinicalTrials.gov has it


def condition_match(patient_terms: Iterable[str], study: dict[str, Any]) -> ConditionMatch | None:
    """The first (patient term, trial term) pair that matches, patient terms in order."""
    terms = trial_terms(study) or []
    trial_words = [(t, words(t)) for t in terms]
    for p in patient_terms:
        for alias in expand(p):
            for t, tw in trial_words:
                if alias <= tw:
                    return ConditionMatch(patient_term=p, trial_term=t)
    return None
