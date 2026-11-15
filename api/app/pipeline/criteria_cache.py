"""SQLite cache of compiled criteria: NCT id + hash of the eligibility fields -> list[Criterion]."""

import hashlib
import json
from typing import Any

from sqlmodel import col, select

from app.db import CompiledCriteriaRow, session_scope, utcnow
from app.schemas import Criterion

# The eligibility-module fields the compiler reads. Changing any of them recompiles.
HASHED_FIELDS = ("eligibilityCriteria", "minimumAge", "maximumAge", "sex")


def eligibility_hash(eligibility: dict[str, Any]) -> str:
    payload = json.dumps({k: eligibility.get(k) for k in HASHED_FIELDS}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _criteria(row: CompiledCriteriaRow) -> list[Criterion]:
    return [Criterion.model_validate(c) for c in row.criteria]


def get(nct_id: str, criteria_hash: str, prompt_version: str) -> list[Criterion] | None:
    with session_scope() as s:
        row = s.get(CompiledCriteriaRow, (nct_id, criteria_hash))
        if row is None or row.prompt_version != prompt_version:
            return None
        return _criteria(row)


def put(
    nct_id: str,
    criteria_hash: str,
    prompt_version: str,
    model: str | None,
    criteria: list[Criterion],
) -> None:
    with session_scope() as s:
        row = s.get(CompiledCriteriaRow, (nct_id, criteria_hash)) or CompiledCriteriaRow(
            nct_id=nct_id, criteria_hash=criteria_hash, prompt_version=prompt_version
        )
        row.prompt_version = prompt_version
        row.model = model
        row.created_at = utcnow()
        row.criteria = [c.model_dump(mode="json") for c in criteria]
        s.add(row)


def latest(nct_id: str) -> list[Criterion]:
    """The most recently compiled criteria for a trial, or [] if it was never compiled."""
    with session_scope() as s:
        row = s.exec(
            select(CompiledCriteriaRow)
            .where(CompiledCriteriaRow.nct_id == nct_id)
            .order_by(col(CompiledCriteriaRow.created_at).desc())
        ).first()
        return _criteria(row) if row else []
