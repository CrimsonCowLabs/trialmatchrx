"""Record each demo patient's match run and closer run into run fixtures for DEMO_MODE=replay.

    uv run python -m scripts.record_demo                       # live, all patients
    uv run python -m scripts.record_demo --patient als         # live, one patient (repeatable)
    uv run python -m scripts.record_demo --patient t2d --nct NCT07271186   # closer on this trial
    uv run python -m scripts.record_demo --from-runs MATCH_RUN_ID CLOSER_RUN_ID [--patient t2d]

A live recording needs ANTHROPIC_API_KEY and runs the real pipeline on the app database (so
`make seed` first: the trials and their compiled criteria come from SQLite), with the same
request the demo patient card sends, then the closer agent on the top trial that isn't
ineligible. `--from-runs` instead saves two finished runs already in the database (a rehearsal
done in the UI), offline; the patient is the one whose note the match run was on, unless
`--patient` says otherwise.

Writes `match-<patient>.json` and `closer-<patient>.json` to DEMO_FIXTURES_DIR (default
data/fixtures/runs), and prints each run's LLM cost from its trace. A run that fails is not
saved. Replay picks the patient by the note it is sent (app/trace/replay.py).
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.config import get_settings
from app.db import init_db
from app.pipeline.closer_agent import anthropic_closer_model, find_trial_match, run_closer
from app.pipeline.compile_criteria import ModelFactory, anthropic_compile_model
from app.pipeline.judge import anthropic_judge_model
from app.pipeline.match_run import run_match
from app.pipeline.parse_patient import anthropic_parse_model
from app.schemas import CloserRequest, MatchRequest, RunKind
from app.trace.replay import RunFixture, export_run, normalize_note, write_fixture
from app.trace.runner import RunWork, traced_run

RADIUS_MI = 100

# HACK(demo): mirrors the patient cards in web/lib/demo.ts by id + note (and the condition and
# radius each card sends), so each recording is of exactly what the pitch submits. Replay finds
# a patient by its note, so keep the notes identical on both sides.
DEMO_PATIENTS: dict[str, dict[str, Any]] = {
    "als": {
        "note": (
            "54-year-old man with ALS (limb onset), symptom onset 14 months ago. ALSFRS-R 41, "
            "bulbar subscore 11, breathing subscore 12. FVC 82% predicted. On riluzole 50 mg "
            "twice daily for 8 months. No non-invasive ventilation or oxygen use. Lives in "
            "Davis, CA."
        ),
        "condition": "amyotrophic lateral sclerosis",
        "radius_mi": RADIUS_MI,
    },
    "ipf": {
        "note": (
            "68-year-old man with idiopathic pulmonary fibrosis diagnosed 2 years ago, UIP "
            "pattern on HRCT. Former smoker with mild emphysema, less extensive than the "
            "fibrosis. FVC 62% predicted, DLCO 38% predicted, FEV1/FVC 0.66. On nintedanib "
            "150 mg twice daily, stable dose for 1 year. No heart failure. Lives in "
            "Sacramento, CA."
        ),
        "condition": "idiopathic pulmonary fibrosis",
        "radius_mi": RADIUS_MI,
    },
    "pah": {
        "note": (
            "47-year-old woman with idiopathic pulmonary arterial hypertension (WHO Group 1), "
            "WHO functional class III. Speaks Spanish only. Right heart catheterization last "
            "year: PVR 7 Wood units. 6-minute walk distance 380 m. On ambrisentan and "
            "tadalafil, stable for 6 months. BMI 27. Lives in Rancho Cordova, CA."
        ),
        "condition": "pulmonary arterial hypertension",
        "radius_mi": RADIUS_MI,
    },
    "t2d": {
        "note": (
            "61-year-old man with type 2 diabetes, HbA1c 8.4%, eGFR 48, on metformin. "
            "Lives in Sacramento."
        ),
        "condition": "type 2 diabetes",
        "radius_mi": RADIUS_MI,
    },
}
DEFAULT_PATIENT = "t2d"


def match_fixture_path(out: Path, patient: str = DEFAULT_PATIENT) -> Path:
    return out / f"match-{patient}.json"


def closer_fixture_path(out: Path, patient: str = DEFAULT_PATIENT) -> Path:
    return out / f"closer-{patient}.json"


def patient_for_note(note: str | None) -> str | None:
    """The demo patient whose note this is (whitespace/case-normalized), if any."""
    wanted = normalize_note(note)
    for patient, request in DEMO_PATIENTS.items():
        if normalize_note(request["note"]) == wanted:
            return patient
    return None


def llm_cost(fixture: RunFixture) -> float | None:
    """The run's summed LLM cost from its trace (each `llm` event's final state); None when no
    event carries a cost (unpriced model, or every call a cache hit)."""
    final = {e.id: e for e in fixture.events if e.kind == "llm"}
    costs = [e.cost_usd for e in final.values() if e.cost_usd is not None]
    return sum(costs) if costs else None


def describe(fixture: RunFixture) -> str:
    cost = llm_cost(fixture)
    priced = f"${cost:.4f}" if cost is not None else "n/a"
    return f"{fixture.kind} run {fixture.run_id}: {len(fixture.events)} events, LLM cost {priced}"


async def _record(kind: RunKind, request: dict[str, Any], work: RunWork) -> str:
    """Run `work` as a traced run (like `start_traced_run`, but awaited); its run id."""
    run_id: str | None = None
    try:
        async with traced_run(kind, request) as run:
            run_id = run.run_id
            run.result = await work(run.recorder)
    except Exception as exc:
        raise RuntimeError(f"{kind} run {run_id} failed, nothing saved: {exc}") from exc
    return run.run_id


def _save(path: Path, fixture: RunFixture, patient: str) -> RunFixture:
    fixture.patient = patient
    write_fixture(path, fixture)
    return fixture


async def record_match(
    out: Path,
    request: dict[str, Any] = DEMO_PATIENTS[DEFAULT_PATIENT],
    *,
    patient: str = DEFAULT_PATIENT,
    model_factory: ModelFactory = anthropic_compile_model,
    parse_model_factory: ModelFactory = anthropic_parse_model,
    judge_model_factory: ModelFactory = anthropic_judge_model,
) -> RunFixture:
    """Run the match pipeline on `request` and save it as `match-<patient>.json`."""
    req = MatchRequest.model_validate(request)
    run_id = await _record(
        "match",
        req.model_dump(mode="json"),
        lambda rec: run_match(
            rec,
            req,
            model_factory=model_factory,
            parse_model_factory=parse_model_factory,
            judge_model_factory=judge_model_factory,
        ),
    )
    return _save(match_fixture_path(out, patient), export_run(run_id), patient)


def demo_trial(match: RunFixture) -> str:
    """The closer's trial: the top-ranked one that isn't ineligible (the demo's "top trial")."""
    for m in (match.result or {}).get("matches", []):
        if m["tier"] != "ineligible":
            return str(m["nct_id"])
    raise RuntimeError("the match run has no trial that isn't ineligible; pass --nct")


async def record_closer(
    out: Path,
    match_run_id: str,
    nct: str,
    *,
    model: BaseChatModel,
    patient: str = DEFAULT_PATIENT,
) -> RunFixture:
    """Run the closer agent on `nct` of a finished match run; save it as
    `closer-<patient>.json`."""
    req = CloserRequest(run_id=match_run_id, nct_id=nct)
    find_trial_match(req.run_id, req.nct_id)  # the route's 404/409 check
    run_id = await _record(
        "closer", req.model_dump(mode="json"), lambda rec: run_closer(rec, req, model=model)
    )
    return _save(closer_fixture_path(out, patient), export_run(run_id), patient)


def save_runs(
    out: Path, match_run_id: str, closer_run_id: str, patient: str | None = None
) -> list[Path]:
    """Save two finished runs from the database as one patient's fixtures (offline)."""
    match, closer = export_run(match_run_id), export_run(closer_run_id)
    if match.kind != "match" or closer.kind != "closer":
        raise RuntimeError(
            f"expected a match run and a closer run, got {match.kind}, {closer.kind}"
        )
    if closer.request.get("run_id") != match.run_id:
        raise RuntimeError(f"closer run {closer.run_id} wasn't run on match run {match.run_id}")
    patient = patient or patient_for_note(match.request.get("note"))
    if patient is None:
        raise RuntimeError(
            f"match run {match.run_id}'s note isn't a demo patient's; pass --patient"
        )
    paths = [match_fixture_path(out, patient), closer_fixture_path(out, patient)]
    _save(paths[0], match, patient)
    _save(paths[1], closer, patient)
    return paths


async def record_live(out: Path, patients: list[str], nct: str | None) -> list[Path]:
    """Record each patient in turn; stops at the first failure (earlier patients stay saved)."""
    paths: list[Path] = []
    total = 0.0
    for patient in patients:
        match = await record_match(out, DEMO_PATIENTS[patient], patient=patient)
        print(f"[{patient}] {describe(match)}")
        trial = nct or demo_trial(match)
        closer = await record_closer(
            out, match.run_id, trial, model=anthropic_closer_model(), patient=patient
        )
        print(f"[{patient}] {describe(closer)} on {trial}")
        total += (llm_cost(match) or 0.0) + (llm_cost(closer) or 0.0)
        paths += [match_fixture_path(out, patient), closer_fixture_path(out, patient)]
    print(f"total LLM cost ${total:.4f}")
    return paths


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=settings.demo_fixtures_dir)
    parser.add_argument(
        "--patient",
        action="append",
        choices=sorted(DEMO_PATIENTS),
        help="record only this patient (repeatable; default: all)",
    )
    parser.add_argument("--nct", help="the closer's trial (default: the top non-ineligible one)")
    parser.add_argument(
        "--from-runs",
        nargs=2,
        metavar=("MATCH_RUN_ID", "CLOSER_RUN_ID"),
        help="save these finished runs from the database instead of recording new ones",
    )
    args = parser.parse_args()
    patients: list[str] = args.patient or list(DEMO_PATIENTS)
    if args.nct and len(patients) != 1:
        parser.error("--nct needs exactly one --patient")
    if args.from_runs and args.patient and len(args.patient) != 1:
        parser.error("--from-runs takes at most one --patient")

    init_db()
    if args.from_runs:
        paths = save_runs(args.out, *args.from_runs, patient=(args.patient or [None])[0])
    else:
        if not settings.anthropic_api_key:
            sys.exit("ANTHROPIC_API_KEY is not set; a live recording needs it (or --from-runs)")
        paths = asyncio.run(record_live(args.out, patients, args.nct))
    for path in paths:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
