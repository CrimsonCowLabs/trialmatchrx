"""The 10 saved ClinicalTrials.gov v2 studies the compiler is tested and scored on.

The route compiles from the ctgov cache (`app.sources.ctgov.get_study`); these fixtures feed
pytest and `scripts/compile_fixtures.py --fixtures` so neither needs the network.
"""

import json
from typing import Any

from app.config import API_DIR

FIXTURE_STUDIES_DIR = API_DIR / "tests" / "fixtures" / "compile" / "studies"


class StudyNotFound(LookupError):
    pass


def load_fixture_study(nct: str) -> dict[str, Any]:
    """The saved raw v2 study JSON for `nct`."""
    path = FIXTURE_STUDIES_DIR / f"{nct}.json"
    if not nct.isalnum() or not path.is_file():
        raise StudyNotFound(nct)
    study: dict[str, Any] = json.loads(path.read_text())
    return study


def fixture_nct_ids() -> list[str]:
    return sorted(p.stem for p in FIXTURE_STUDIES_DIR.glob("NCT*.json"))
