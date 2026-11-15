"""Record the demo patient's match run and closer run into run fixtures for DEMO_MODE=replay.

    uv run python -m scripts.record_demo                     # live: needs ANTHROPIC_API_KEY
    uv run python -m scripts.record_demo --nct NCT07271186   # the closer on this trial
    uv run python -m scripts.record_demo --from-runs MATCH_RUN_ID CLOSER_RUN_ID

A live recording runs the real pipeline on the app database (so `make seed` first: the trials
and their compiled criteria come from SQLite), with the same request the /match page sends,
then the closer agent on the top trial that isn't ineligible. `--from-runs` instead saves two
finished runs already in the database (a rehearsal done in the UI), offline.

Writes `match.json` and `closer-<NCT>.json` to DEMO_FIXTURES_DIR (default data/fixtures/runs).
A run that fails is not saved.
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
from app.trace.replay import RunFixture, export_run, write_fixture
from app.trace.runner import RunWork, traced_run

# HACK(demo): a copy of the request web/app/match/page.tsx sends (its DEMO_NOTE, condition and
# radius), so the recording is of exactly what the pitch submits. Keep the two in sync.
DEMO_REQUEST: dict[str, Any] = {
    "note": (
        "61-year-old man with type 2 diabetes, HbA1c 8.4%, eGFR 48, on metformin. "
        "Lives in Sacramento."
    ),
    "condition": "type 2 diabetes",
    "radius_mi": 100,
}


def match_fixture_path(out: Path) -> Path:
    return out / "match.json"


def closer_fixture_path(out: Path, nct: str) -> Path:
    return out / f"closer-{nct}.json"


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


async def record_match(
    out: Path,
    request: dict[str, Any] = DEMO_REQUEST,
    *,
    model_factory: ModelFactory = anthropic_compile_model,
    parse_model_factory: ModelFactory = anthropic_parse_model,
    judge_model_factory: ModelFactory = anthropic_judge_model,
) -> RunFixture:
    """Run the match pipeline on `request` and save it as `match.json`."""
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
    fixture = export_run(run_id)
    write_fixture(match_fixture_path(out), fixture)
    return fixture


def demo_trial(match: RunFixture) -> str:
    """The closer's trial: the top-ranked one that isn't ineligible (the demo's "top trial")."""
    for m in (match.result or {}).get("matches", []):
        if m["tier"] != "ineligible":
            return str(m["nct_id"])
    raise RuntimeError("the match run has no trial that isn't ineligible; pass --nct")


async def record_closer(
    out: Path, match_run_id: str, nct: str, *, model: BaseChatModel
) -> RunFixture:
    """Run the closer agent on `nct` of a finished match run; save it as `closer-<NCT>.json`."""
    req = CloserRequest(run_id=match_run_id, nct_id=nct)
    find_trial_match(req.run_id, req.nct_id)  # the route's 404/409 check
    run_id = await _record(
        "closer", req.model_dump(mode="json"), lambda rec: run_closer(rec, req, model=model)
    )
    fixture = export_run(run_id)
    write_fixture(closer_fixture_path(out, nct), fixture)
    return fixture


def save_runs(out: Path, match_run_id: str, closer_run_id: str) -> list[Path]:
    """Save two finished runs from the database as the demo fixtures (offline)."""
    match, closer = export_run(match_run_id), export_run(closer_run_id)
    if match.kind != "match" or closer.kind != "closer":
        raise RuntimeError(
            f"expected a match run and a closer run, got {match.kind}, {closer.kind}"
        )
    if closer.request.get("run_id") != match.run_id:
        raise RuntimeError(f"closer run {closer.run_id} wasn't run on match run {match.run_id}")
    return [
        write_fixture(match_fixture_path(out), match),
        write_fixture(closer_fixture_path(out, str(closer.request["nct_id"])), closer),
    ]


async def record_live(out: Path, nct: str | None) -> list[Path]:
    match = await record_match(out)
    print(f"match run {match.run_id}: {len(match.events)} events")
    trial = nct or demo_trial(match)
    closer = await record_closer(out, match.run_id, trial, model=anthropic_closer_model())
    print(f"closer run {closer.run_id} on {trial}: {len(closer.events)} events")
    return [match_fixture_path(out), closer_fixture_path(out, trial)]


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=settings.demo_fixtures_dir)
    parser.add_argument("--nct", help="the closer's trial (default: the top non-ineligible one)")
    parser.add_argument(
        "--from-runs",
        nargs=2,
        metavar=("MATCH_RUN_ID", "CLOSER_RUN_ID"),
        help="save these finished runs from the database instead of recording new ones",
    )
    args = parser.parse_args()

    init_db()
    if args.from_runs:
        paths = save_runs(args.out, *args.from_runs)
    else:
        if not settings.anthropic_api_key:
            sys.exit("ANTHROPIC_API_KEY is not set; a live recording needs it (or --from-runs)")
        paths = asyncio.run(record_live(args.out, args.nct))
    for path in paths:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
