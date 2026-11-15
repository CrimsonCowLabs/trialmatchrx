"""Access barriers (issue #53): criteria that shut people out for reasons other than health.

    barrier = classify("Able to read and write English")        # "language"
    criteria = await flag_access_barriers(nct_id, criteria, rec)  # traced `access_barriers` rule

Rule-based on purpose: keyword / phrase patterns over the criterion's verbatim text, no LLM, so
it runs on criteria already in the compile cache without recompiling them (the flag is set where
criteria are served, never stored as part of the compile). One barrier per criterion: the first
category in BARRIER_ORDER whose patterns match.

Patterns aim to miss rather than over-flag. A criterion about the people running the study
(site staff, the investigator) rather than the patient is not a patient barrier: when a staff
term is the subject (it comes before any patient term) the criterion is not flagged.
"""

import re
from collections.abc import Sequence

from app.schemas import AccessBarrier, Criterion
from app.trace.recorder import TraceRecorder

RULES_VERSION = "2"

_ENGLISH_VERBS = r"read|write|speak|understand|comprehend|communicate|fluent|literate|proficient"

PATTERNS: dict[AccessBarrier, tuple[str, ...]] = {
    "language": (
        rf"\b(?:{_ENGLISH_VERBS})\w*\b[^.;]{{0,40}}\benglish\b",
        r"\benglish[- ](?:speak\w*|language|literate|literacy|proficien\w*|fluen\w*)\b",
        r"\bnon[- ]?english\b",
        r"\blanguage barriers?\b",
        # Reading at all; "computer / digital literacy" is technology.
        r"(?<!computer\s)(?<!digital\s)\b(?:il)?litera(?:te|cy)\b",
    ),
    "visit_burden": (
        # How often: "weekly study visits", "frequent visits".
        r"\b(?:frequent|weekly|daily|twice[- ]weekly|bi-?weekly|monthly|numerous)"
        r"\s+(?:(?:study|clinic|site|in[- ]person|on[- ]site|outpatient|scheduled)\s+)*visits\b",
        # How many, only after a verb of attending: "complete 14 in-person visits", not a
        # measurement "at two clinic visits" or "on 2 visits".
        r"\b(?:attend|complete|make|undergo|return\s+for|come\s+in\s+for)\w*\s+"
        r"(?:at\s+least\s+|up\s+to\s+)?(?:multiple|many|several|\d+|two|three|four|five|six"
        r"|seven|eight|nine|ten|twelve)\s+"
        r"(?:(?:study|clinic|site|in[- ]person|on[- ]site|outpatient|scheduled)\s+)*visits\b",
        # Staying at the site: "overnight stays", "inpatient period" (not "overnight fast", nor a
        # past "inpatient stay / hospitalization" for heart failure).
        r"\b(?:overnight|in[- ]clinic|in[- ]house|residential)\s+(?:stays?|visits?|periods?"
        r"|confinement)\b",
        r"\bin-?patient\s+(?:periods?|confinement)\b",
        # Confined to the study clinic, not "confined to a hospital or nursing home" (health).
        r"\bconfine(?:d|ment)\b[^.;]{0,30}\b(?:clinic|unit|site|centre|center)\b",
        r"\b(?:remain|stay|reside)\w*\b[^.;]{0,20}\b(?:at|in)\s+the\s+(?:clinical\s+)?"
        r"(?:study\s+|research\s+)?(?:site|clinic|unit|centre|center)\b",
        r"\btravel\w*\b[^.;]{0,30}\bto\s+the\s+(?:study\s+|trial\s+|research\s+)?"
        r"(?:site|clinic|centre|center|hospital)\b",
    ),
    "technology": (
        r"\bsmart\s?phones?\b|\b(?:mobile|cell(?:ular)?)\s?phones?\b",
        r"\binternet\b|\bwi-?fi\b|\bbroadband\b|\bbluetooth\b",
        r"\be-?diar(?:y|ies)\b|\belectronic\s+diar(?:y|ies)\b",
        r"\b(?:mobile|smartphone|study|web)\s+app(?:lication)?s?\b|\bweb[- ]based\b",
        r"\bonline\s+(?:portal|questionnaires?|surveys?)\b",
        r"\bemail\s+(?:address|account)\b|\blaptop\b",
        r"\bcomputer\b(?!\s+tomograph)|\b(?:computer|digital)\s+litera(?:te|cy)\b",
        r"\bvideo\s+(?:calls?|visits?|conferenc\w*)\b",
    ),
    "support": (
        r"\bcare[- ]?givers?\b|\bcarers?\b",
        # "study partner", not a sexual partner (contraception criteria).
        r"\bstudy\s+(?:partner|companion)s?\b|\binformants?\b",
        # "transportation", not "co-transporter" (SGLT2 inhibitors).
        r"\btransportation\b|\bown\s+(?:car|vehicle)\b|\bdriver'?s\s+licen[cs]e\b",
        r"\baccompan(?:ied|y)\b[^.;]{0,30}\b(?:adult|caregiver|family|partner|companion|person)\b",
        r"\b(?:live|lives|living)\s+alone\b",
    ),
}
BARRIER_ORDER: tuple[AccessBarrier, ...] = ("language", "visit_burden", "technology", "support")

_COMPILED = {b: [re.compile(p, re.I) for p in ps] for b, ps in PATTERNS.items()}
_STAFF = re.compile(
    r"\b(?:site|study|research|clinical)\s+(?:staff|personnel|team|coordinators?)\b"
    r"|\binvestigators?\b",
    re.I,
)
_PATIENT = re.compile(
    r"\b(?:patients?|participants?|subjects?|volunteers?|individuals?|persons?|caregivers?"
    r"|you|he|she|they)\b",
    re.I,
)


def _match(text: str) -> tuple[AccessBarrier, str] | None:
    for barrier in BARRIER_ORDER:
        for pattern in _COMPILED[barrier]:
            m = pattern.search(text)
            if m:
                return barrier, m.group(0)
    return None


# "In the opinion of the investigator, the participant ...", "as judged by the investigator":
# the investigator judges the patient, so the criterion is still about the patient.
_JUDGMENT = re.compile(
    r"\b(?:opinion|judge?ment|discretion|assessment)\s+of\s+(?:the\s+)?(?:\w+\s+)?investigators?"
    r"|\binvestigators?'?s?\s+(?:opinion|judge?ment|discretion|assessment)"
    r"|\b(?:judged|assessed|determined|deemed)\s+by\s+(?:the\s+)?(?:\w+\s+)?investigators?",
    re.I,
)


def _about_staff(text: str) -> bool:
    """The study's people, not the patient, are the subject: a staff term comes first."""
    text = _JUDGMENT.sub(" ", text)
    staff = _STAFF.search(text)
    if staff is None:
        return False
    patient = _PATIENT.search(text)
    return patient is None or staff.start() < patient.start()


def explain(text: str) -> tuple[AccessBarrier, str] | None:
    """The barrier and the phrase that matched, or None."""
    found = _match(text)
    if found is None or _about_staff(text):
        return None
    return found


def classify(text: str) -> AccessBarrier | None:
    found = explain(text)
    return found[0] if found else None


def _flagged(criteria: Sequence[Criterion]) -> tuple[list[Criterion], dict[str, dict[str, str]]]:
    """The criteria with `access_barrier` set, and {criterion id: {barrier, match}} for those
    flagged. The one place the flag is applied, traced or not."""
    out, flagged = [], {}
    for c in criteria:
        found = explain(c.text)
        if found:
            flagged[c.id] = {"barrier": found[0], "match": found[1]}
        out.append(c.model_copy(update={"access_barrier": found[0] if found else None}))
    return out, flagged


def with_access_barriers(criteria: Sequence[Criterion]) -> list[Criterion]:
    """Each criterion with `access_barrier` set from its text (pure; prefer the traced
    `flag_access_barriers` wherever a recorder exists)."""
    return _flagged(criteria)[0]


async def flag_access_barriers(
    nct_id: str, criteria: Sequence[Criterion], rec: TraceRecorder
) -> list[Criterion]:
    """`with_access_barriers` as a traced `access_barriers` rule step: the output names every
    flagged criterion with its barrier and the phrase that matched."""
    async with rec.step(
        "access_barriers",
        "rule",
        {"nct": nct_id, "criteria": len(criteria), "rules_version": RULES_VERSION},
    ) as s:
        out, flagged = _flagged(criteria)
        s.output = {"flagged": flagged}
        n = len(flagged)
        detail = ", ".join(f"{cid} {f['barrier']}" for cid, f in flagged.items())
        s.note = (
            f"{nct_id}: {n} access barrier{'' if n == 1 else 's'} ({detail})"
            if n
            else f"{nct_id}: no access barriers"
        )
    return out
