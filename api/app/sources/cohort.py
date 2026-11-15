"""The feasibility cohort: synthetic PatientFacts in the `cohort` table, and the process-wide
DataFrame built from it.

    replace_cohort([(patient_id, source, facts), ...])   # scripts/load_cohort.py
    cohort = get_cohort()                                # feasibility route, read once

The DataFrame is built on first use (or at startup) and kept for the life of the process. An
empty table isn't cached, so a server started before `make seed` picks the cohort up once it
lands; reloading a new cohort into a running server needs a restart (or `reset_cohort()`).
"""

from collections.abc import Iterable

from sqlmodel import delete, select

from app.db import CohortPatientRow, session_scope
from app.pipeline.feasibility import Cohort
from app.schemas import PatientFacts

_cohort: Cohort | None = None


def replace_cohort(patients: Iterable[tuple[str, str, PatientFacts]]) -> int:
    """Swap the whole table for these (patient id, source file, facts) rows. Returns the count."""
    rows = [
        CohortPatientRow(id=pid, source=source, facts=facts.model_dump(mode="json"))
        for pid, source, facts in patients
    ]
    with session_scope() as s:
        s.exec(delete(CohortPatientRow))
        s.add_all(rows)
    reset_cohort()
    return len(rows)


def read_facts() -> list[PatientFacts]:
    """Every cohort patient, in id order (so the DataFrame's row order is stable)."""
    with session_scope() as s:
        rows = s.exec(select(CohortPatientRow).order_by(CohortPatientRow.id)).all()
        return [PatientFacts.model_validate(r.facts) for r in rows]


def get_cohort() -> Cohort:
    """The process-wide cohort (FastAPI dependency; tests override it)."""
    global _cohort
    if _cohort is None:
        cohort = Cohort.from_facts(read_facts())
        if cohort.size == 0:
            return cohort
        _cohort = cohort
    return _cohort


def reset_cohort() -> None:
    global _cohort
    _cohort = None
