"""Where the compiler gets a raw ClinicalTrials.gov v2 study. One seam, one function.

# HACK(demo): replaced by ctgov cache in #2 — `load_study` reads saved fixture studies from
# api/tests/fixtures/compile/studies/ until `app.sources.ctgov.get_study` exists; then this
# body becomes `return await ctgov.get_study(nct, recorder=recorder)`.
"""

import json
from typing import Any

from app.config import API_DIR
from app.trace.recorder import TraceRecorder

FIXTURE_STUDIES_DIR = API_DIR / "tests" / "fixtures" / "compile" / "studies"


class StudyNotFound(LookupError):
    pass


async def load_study(nct: str, *, recorder: TraceRecorder | None = None) -> dict[str, Any]:
    """The raw v2 study JSON for `nct` (same signature as #2's `ctgov.get_study`)."""
    # HACK(demo): replaced by ctgov cache in #2
    path = FIXTURE_STUDIES_DIR / f"{nct}.json"
    if not nct.isalnum() or not path.is_file():
        raise StudyNotFound(nct)
    study: dict[str, Any] = json.loads(path.read_text())
    return study


def fixture_nct_ids() -> list[str]:
    return sorted(p.stem for p in FIXTURE_STUDIES_DIR.glob("NCT*.json"))
