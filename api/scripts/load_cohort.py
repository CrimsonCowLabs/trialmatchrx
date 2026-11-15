"""Load Synthea FHIR bundles into the feasibility cohort table (SPEC.md pipeline 6). No network.

    make cohort                                   # generate 1,000 patients if needed, then this
    uv run python -m scripts.load_cohort --dir ../data/synthea/output/fhir

Each patient bundle is mapped to PatientFacts by the same deterministic mapper the FHIR match
path uses (`synthea.map_bundle`), and the table is replaced as a whole. Synthea's
hospital / practitioner bundles and anything that isn't one-Patient bundle are skipped.
"""

import argparse
import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path

from app.config import REPO_DIR
from app.db import init_db
from app.schemas import PatientFacts
from app.sources.cohort import replace_cohort
from app.sources.synthea import InvalidBundle, check_bundle, map_bundle

DEFAULT_DIR = REPO_DIR / "data" / "synthea" / "output" / "fhir"


def read_bundles(
    directory: Path, as_of: dt.date, skipped: list[str]
) -> Iterator[tuple[str, str, PatientFacts]]:
    """(patient id, file name, facts) per patient bundle; unusable files go to `skipped`."""
    for path in sorted(directory.glob("*.json")):
        try:
            bundle = json.loads(path.read_text())
            patient = check_bundle(bundle)
        except (InvalidBundle, json.JSONDecodeError) as exc:
            skipped.append(f"{path.name}: {exc}")
            continue
        facts = map_bundle(bundle, as_of=as_of).facts
        yield str(patient.get("id") or path.stem), path.name, facts


def _has(facts: PatientFacts, name: str) -> bool:
    return any(name in str(c.value).lower() for c in facts.conditions)


def main(directory: Path, as_of: dt.date) -> None:
    if not directory.is_dir():
        raise SystemExit(f"load_cohort: no bundles at {directory}; run `make cohort` first")
    init_db()
    skipped: list[str] = []
    patients = list(read_bundles(directory, as_of, skipped))
    count = replace_cohort(patients)
    facts = [f for _, _, f in patients]
    t2d = [f for f in facts if _has(f, "type 2 diabetes")]
    print(
        f"cohort: {count} patients loaded from {directory} ({len(skipped)} files skipped); "
        f"T2D {len(t2d)}, CKD {sum(_has(f, 'chronic kidney disease') for f in facts)}, "
        f"eGFR on file {sum('egfr' in f.labs for f in facts)} "
        f"(T2D with eGFR {sum('egfr' in f.labs for f in t2d)}), "
        f"HbA1c on file {sum('hba1c' in f.labs for f in facts)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="Synthea fhir/ output")
    parser.add_argument(
        "--as-of",
        type=dt.date.fromisoformat,
        default=dt.date.today(),
        help="date ages are computed on (default: today)",
    )
    args = parser.parse_args()
    main(args.dir, args.as_of)
