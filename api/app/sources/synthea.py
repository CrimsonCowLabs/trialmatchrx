"""Synthea FHIR bundle -> PatientFacts (SPEC.md pipeline 1, FHIR path). Deterministic, no LLM.

    facts = await parse_bundle(rec, bundle)               # match run: one traced step
    facts = facts_from_bundle(bundle, as_of=some_date)   # pure (cohort loader, tests)

Plain dict parsing of a FHIR R4 Bundle (no FHIR library). Maps Patient (age, sex, geolocation),
active Conditions, Observations (LOINC: HbA1c 4548-4, eGFR 33914-3 / 62238-1, BMI 39156-5, BP
panel 85354-9, smoking status 72166-2) and active MedicationRequests. Per lab / vital the most
recent reading in the canonical unit wins, with its unit and date. Anything the bundle doesn't
have stays empty / None: nothing is inferred.
"""

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.pipeline.predicate_fields import LAB_UNITS, VITAL_UNITS, normalize_unit
from app.schemas import Fact, PatientFacts
from app.trace.recorder import TraceRecorder

GEOLOCATION = "http://hl7.org/fhir/StructureDefinition/geolocation"

# LOINC code -> (PatientFacts section, key). SPEC.md: HbA1c 4548-4, eGFR 33914-3 / 62238-1,
# BMI 39156-5, BP panel 85354-9 (its systolic / diastolic components).
LOINC: dict[str, tuple[str, str]] = {
    "4548-4": ("labs", "hba1c"),
    "33914-3": ("labs", "egfr"),
    "62238-1": ("labs", "egfr"),
    "39156-5": ("vitals", "bmi"),
    "8480-6": ("vitals", "sbp"),
    "8462-4": ("vitals", "dbp"),
}
BP_PANEL = "85354-9"
CANONICAL_UNITS = {"labs": LAB_UNITS, "vitals": VITAL_UNITS}
# UCUM spellings Synthea writes -> the canonical unit (after `normalize_unit`).
UCUM_ALIASES = {"ml/min/{1.73_m2}": "ml/min/1.73m2", "mm[hg]": "mmhg"}

# HACK(demo): one hand-picked rename, not a terminology map. SNOMED codes whose Synthea display
# doesn't contain the name compiled predicates use (`has "type 2 diabetes"` vs "Diabetes
# mellitus type 2 (disorder)"). Everything else keeps its display, minus the semantic tag.
CONDITION_NAMES = {"44054006": "type 2 diabetes mellitus"}
SMOKING_STATUS = "72166-2"
# SNOMED smoking-status answers Synthea writes. "Ex-smoker" is not a current smoker; anything
# else (e.g. 266927001 "consumption unknown") leaves `smoker` None.
SMOKING_CODES: dict[str, bool] = {
    "266919005": False,  # Never smoked tobacco
    "8517006": False,  # Ex-smoker
    "77176002": True,  # Smoker
    "449868002": True,  # Smokes tobacco daily
    "428041000124106": True,  # Occasional tobacco smoker
    "230059006": True,  # Occasional cigarette smoker
}
SEMANTIC_TAG = re.compile(r"\s*\((disorder|finding|situation|morphologic abnormality)\)\s*$")


def _entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Bundle entries that carry a resource (malformed entries are skipped)."""
    return [
        e
        for e in bundle.get("entry") or []
        if isinstance(e, dict) and isinstance(e.get("resource"), dict)
    ]


def _resources(bundle: dict[str, Any], resource_type: str) -> list[dict[str, Any]]:
    return [
        e["resource"]
        for e in _entries(bundle)
        if e["resource"].get("resourceType") == resource_type
    ]


def _date(value: Any) -> dt.date | None:
    """`2026-09-20` or `2026-09-20T09:30:00-08:00` -> date (the local date as written)."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _age(birth: dt.date | None, on: dt.date) -> int | None:
    if birth is None:
        return None
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _location(patient: dict[str, Any]) -> tuple[float | None, float | None]:
    """Synthea's geolocation extension on the Patient's address."""
    for address in patient.get("address") or []:
        if not isinstance(address, dict):
            continue
        for ext in address.get("extension") or []:
            if not isinstance(ext, dict) or ext.get("url") != GEOLOCATION:
                continue
            parts = {
                x.get("url"): x.get("valueDecimal")
                for x in ext.get("extension") or []
                if isinstance(x, dict)
            }
            lat, lon = _number(parts.get("latitude")), _number(parts.get("longitude"))
            if lat is not None and lon is not None:
                return lat, lon
    return None, None


def _codes(concept: dict[str, Any] | None, system: str) -> list[str]:
    return [
        c["code"]
        for c in (concept or {}).get("coding") or []
        if c.get("system") == system and isinstance(c.get("code"), str)
    ]


def _loinc_codes(concept: dict[str, Any] | None) -> list[str]:
    return _codes(concept, "http://loinc.org")


def _snomed_codes(concept: dict[str, Any] | None) -> list[str]:
    return _codes(concept, "http://snomed.info/sct")


def _quantities(obs: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(LOINC code, valueQuantity) pairs: the observation's own value, and for a BP panel each
    component's."""
    codes = _loinc_codes(obs.get("code"))
    if BP_PANEL in codes:
        return [
            (code, comp.get("valueQuantity") or {})
            for comp in obs.get("component") or []
            for code in _loinc_codes(comp.get("code"))
        ]
    return [(code, obs.get("valueQuantity") or {}) for code in codes]


def _canonical_unit(unit: Any, canonical: str) -> bool:
    if not isinstance(unit, str):
        return False
    norm = normalize_unit(unit)
    return UCUM_ALIASES.get(norm, norm) == normalize_unit(canonical)


def _measurements(
    observations: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Fact]], list[str]]:
    """The most recent reading per lab / vital key, and why any reading was dropped."""
    latest: dict[tuple[str, str], tuple[dt.date, int, Fact]] = {}
    dropped: list[str] = []
    for index, obs in enumerate(observations):
        when = _date(obs.get("effectiveDateTime"))
        for code, qty in _quantities(obs):
            if code not in LOINC:
                continue
            section, key = LOINC[code]
            canonical = CANONICAL_UNITS[section][key]
            value = _number(qty.get("value"))
            label = f"{section}.{key} ({obs.get('id')})"
            if value is None:
                dropped.append(f"{label}: no numeric value")
                continue
            if not _canonical_unit(qty.get("unit"), canonical):
                dropped.append(f"{label}: unit {qty.get('unit')!r} is not {canonical!r}")
                continue
            # Newest date wins; an undated reading loses to any dated one; ties: later entry.
            rank = (when or dt.date.min, index)
            current = latest.get((section, key))
            if current is None or rank > current[:2]:
                fact = Fact(value=value, unit=canonical, date=when)
                latest[(section, key)] = (*rank, fact)
    out: dict[str, dict[str, Fact]] = {"labs": {}, "vitals": {}}
    for (section, key), (_, _, fact) in sorted(latest.items()):
        out[section][key] = fact
    return out, dropped


def _display(concept: dict[str, Any] | None) -> str | None:
    concept = concept or {}
    for coding in concept.get("coding") or []:
        if isinstance(coding.get("display"), str) and coding["display"].strip():
            return str(coding["display"]).strip()
    text = concept.get("text")
    return text.strip() if isinstance(text, str) and text.strip() else None


def _status_codes(concept: Any) -> set[str]:
    coding = concept.get("coding") if isinstance(concept, dict) else None
    return {
        c["code"] for c in coding or [] if isinstance(c, dict) and isinstance(c.get("code"), str)
    }


def _is_active(condition: dict[str, Any]) -> bool:
    """Synthea marks a cured condition `resolved` and gives it an abatement date. A condition
    verified as refuted or entered in error isn't the patient's either."""
    if condition.get("abatementDateTime"):
        return False
    if _status_codes(condition.get("clinicalStatus")) & {"resolved", "inactive", "remission"}:
        return False
    return not _status_codes(condition.get("verificationStatus")) & {"refuted", "entered-in-error"}


def _conditions(conditions: list[dict[str, Any]]) -> list[Fact]:
    """Active conditions, one per name (earliest onset), in bundle order."""
    out: dict[str, Fact] = {}
    for condition in conditions:
        if not _is_active(condition):
            continue
        concept = condition.get("code")
        named = [CONDITION_NAMES[c] for c in _snomed_codes(concept) if c in CONDITION_NAMES]
        display = _display(concept)
        name = named[0] if named else SEMANTIC_TAG.sub("", display) if display else None
        if not name:
            continue
        onset = _date(condition.get("onsetDateTime"))
        seen = out.get(name.lower())
        if seen is None or (onset and (seen.date is None or onset < seen.date)):
            out[name.lower()] = Fact(value=name, date=onset)
    return list(out.values())


def _medication_concept(
    request: dict[str, Any], by_url: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    if isinstance(request.get("medicationCodeableConcept"), dict):
        return dict(request["medicationCodeableConcept"])
    ref = (request.get("medicationReference") or {}).get("reference")
    medication = by_url.get(ref) if isinstance(ref, str) else None
    return medication.get("code") if medication else None


def _meds(bundle: dict[str, Any]) -> list[Fact]:
    """Active MedicationRequests, one per drug (latest authored), in bundle order."""
    by_url = {e["fullUrl"]: e["resource"] for e in _entries(bundle) if "fullUrl" in e}
    out: dict[str, Fact] = {}
    for request in _resources(bundle, "MedicationRequest"):
        if request.get("status") != "active":
            continue
        name = _display(_medication_concept(request, by_url))
        if not name:
            continue
        authored = _date(request.get("authoredOn"))
        seen = out.get(name.lower())
        if seen is None or (authored and (seen.date is None or authored > seen.date)):
            out[name.lower()] = Fact(value=name, date=authored)
    return list(out.values())


def _smoker(observations: list[dict[str, Any]]) -> bool | None:
    """The most recent tobacco smoking status (LOINC 72166-2); None if unknown or absent."""
    latest: tuple[dt.date, int, bool | None] | None = None
    for index, obs in enumerate(observations):
        if SMOKING_STATUS not in _loinc_codes(obs.get("code")):
            continue
        rank = (_date(obs.get("effectiveDateTime")) or dt.date.min, index)
        if latest is None or rank > latest[:2]:
            codes = _snomed_codes(obs.get("valueCodeableConcept"))
            status = next((SMOKING_CODES[c] for c in codes if c in SMOKING_CODES), None)
            latest = (*rank, status)
    return latest[2] if latest else None


class InvalidBundle(ValueError):
    """Not a FHIR Bundle holding exactly one Patient."""


def check_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """The bundle's one Patient resource, or InvalidBundle. Cheap enough to run on a request."""
    if bundle.get("resourceType") != "Bundle" or not isinstance(bundle.get("entry"), list):
        raise InvalidBundle("fhir_bundle must be a FHIR Bundle with an entry list")
    patients = _resources(bundle, "Patient")
    if len(patients) != 1:
        raise InvalidBundle(f"fhir_bundle must hold exactly one Patient, found {len(patients)}")
    return patients[0]


@dataclass(frozen=True)
class BundleMapping:
    facts: PatientFacts
    missing: list[str]  # mapped fields the bundle had no usable data for, left empty
    dropped: list[str]  # readings that were present but unusable, and why


def map_bundle(bundle: dict[str, Any], *, as_of: dt.date) -> BundleMapping:
    """Map one patient's bundle. `as_of` is the date age is computed on (or the death date)."""
    patient = check_bundle(bundle)
    gender = patient.get("gender")
    on = _date(patient.get("deceasedDateTime")) or as_of
    lat, lon = _location(patient)
    observations = _resources(bundle, "Observation")
    measured, dropped = _measurements(observations)
    facts = PatientFacts(
        age=_age(_date(patient.get("birthDate")), on),
        sex=gender if gender in ("female", "male") else None,
        conditions=_conditions(_resources(bundle, "Condition")),
        labs=measured["labs"],
        vitals=measured["vitals"],
        meds=_meds(bundle),
        pregnant=None,  # not mapped from FHIR; unknown, never guessed
        smoker=_smoker(observations),
        lat=lat,
        lon=lon,
    )
    present = {"labs": facts.labs, "vitals": facts.vitals}
    mapped = dict.fromkeys(LOINC.values())  # (section, key) in table order, deduplicated
    missing = [f"{sec}.{key}" for sec, key in mapped if key not in present[sec]]
    scalars = {"age": facts.age, "sex": facts.sex, "smoker": facts.smoker, "lat/lon": facts.lat}
    missing += [name for name, value in scalars.items() if value is None]
    return BundleMapping(facts, missing, dropped)


def facts_from_bundle(bundle: dict[str, Any], *, as_of: dt.date) -> PatientFacts:
    return map_bundle(bundle, as_of=as_of).facts


async def parse_bundle(
    rec: TraceRecorder, bundle: dict[str, Any], *, as_of: dt.date | None = None
) -> PatientFacts:
    """The FHIR path of the patient parse, traced as one `parse_patient` step (no LLM).
    `as_of` defaults to today."""
    counts = Counter(e["resource"].get("resourceType") for e in _entries(bundle))
    step_input = {"source": "fhir_bundle", "resources": dict(counts)}
    async with rec.step("parse_patient", "step", step_input) as s:
        mapping = map_bundle(bundle, as_of=as_of or dt.date.today())
        facts = mapping.facts
        s.output = {
            "patient": facts.model_dump(mode="json"),
            "missing": mapping.missing,
            "dropped": mapping.dropped,
        }
        s.note = (
            f"FHIR bundle: {len(facts.conditions)} conditions, {len(facts.labs)} labs, "
            f"{len(facts.vitals)} vitals, {len(facts.meds)} meds"
            + (f"; missing {', '.join(mapping.missing)}" if mapping.missing else "")
        )
    return facts
