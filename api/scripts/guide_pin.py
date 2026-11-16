"""Pin, unpin and list the first-time guide's recorded runs (the `guide_pins` table).

    uv run python -m scripts.guide_pin                            # list; exit 0 if all pinned
    uv run python -m scripts.guide_pin als RUN_ID [--trial NCT]   # als, ipf, ipf_flip: match run
    uv run python -m scripts.guide_pin pah RUN_ID                 # closer run; trial from it
    uv run python -m scripts.guide_pin feasibility --trial NCT    # a cached trial, no run
    uv run python -m scripts.guide_pin --remove STEP

In prod, inside the API container (WORKDIR /app/api, no make):

    ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api \\
        python -m scripts.guide_pin als RUN_ID'

A pin needs a run of the step's kind that finished `done`; `--trial` on a match step must be
one of that run's matches. Pinning a step again replaces its pin. A refusal changes nothing and
exits 2. The list shows every step as pinned / MISSING / RUN GONE and exits 1 unless every step
is pinned and every pinned run still exists: the check to run before judging. The judge-facing
API only reads these pins (GET /api/guide).
"""

import argparse
import sys
from dataclasses import dataclass
from typing import get_args

from app.db import RunRow, init_db
from app.schemas import GuidePin, GuideStep, RunKind
from app.sources.ctgov import cached_study
from app.trace import store

STEPS: tuple[GuideStep, ...] = get_args(GuideStep)
RUN_KIND: dict[GuideStep, RunKind] = {
    "als": "match",
    "ipf": "match",
    "ipf_flip": "match",
    "pah": "closer",
}


class PinRefused(Exception):
    """A pin the script won't write; the message says why."""


@dataclass(frozen=True)
class Pin:
    step: GuideStep
    run_id: str | None
    nct_id: str | None


def parse_step(value: str) -> GuideStep:
    for step in STEPS:
        if step == value:
            return step
    raise PinRefused(f"unknown step {value!r}; steps are {', '.join(STEPS)}")


def finished_run(run_id: str, kind: RunKind, step: GuideStep) -> RunRow:
    """The run, if it exists, is of `kind` and finished `done`."""
    run = store.get_run(run_id)
    if run is None:
        raise PinRefused(f"no run {run_id!r}")
    if run.kind != kind:
        raise PinRefused(f"run {run_id} is a {run.kind} run; {step} needs a {kind} run")
    if run.status != "done":
        raise PinRefused(f"run {run_id} is {run.status}, not done")
    return run


def match_ncts(run: RunRow) -> list[str]:
    """The trials a match run matched, in rank order."""
    return [str(m["nct_id"]) for m in (run.result or {}).get("matches", [])]


def resolve_pin(step: GuideStep, run_id: str | None, trial: str | None) -> Pin:
    """The pin `step run_id --trial trial` asks for, or PinRefused."""
    if step == "feasibility":
        if run_id is not None:
            raise PinRefused("feasibility takes no run_id, only --trial NCT")
        if trial is None:
            raise PinRefused("feasibility needs --trial NCT")
        if cached_study(trial) is None:
            raise PinRefused(f"{trial} is not in the trials cache")
        return Pin(step, None, trial)

    kind = RUN_KIND[step]
    if run_id is None:
        raise PinRefused(f"{step} needs a run_id (a {kind} run)")
    run = finished_run(run_id, kind, step)
    if kind == "closer":
        if trial is not None:
            raise PinRefused(f"{step} takes its trial from the closer run; drop --trial")
        return Pin(step, run_id, str(run.request["nct_id"]))
    if trial is not None:
        ncts = match_ncts(run)
        if trial not in ncts:
            raise PinRefused(
                f"{trial} is not among run {run_id}'s matches: {', '.join(ncts) or '(none)'}"
            )
    return Pin(step, run_id, trial)


def pin_status(pin: GuidePin | None) -> str:
    if pin is None:
        return "MISSING"
    if pin.run_id is not None and not pin.run_exists:
        return "RUN GONE"
    return "pinned"


def report(pins: list[GuidePin]) -> tuple[list[str], bool]:
    """One line per guide step (unpinned ones too) and a summary; True when nothing's
    missing."""
    by_step = {p.step: p for p in pins}
    width = max(len(s) for s in STEPS)
    lines: list[str] = []
    bad = 0
    for step in STEPS:
        pin = by_step.get(step)
        status = pin_status(pin)
        bad += status != "pinned"
        run_id = (pin.run_id if pin else None) or "-"
        nct = (pin.nct_id if pin else None) or "-"
        lines.append(f"{step:<{width}}  {status:<8}  run {run_id}  trial {nct}")
    lines.append(
        f"all {len(STEPS)} steps pinned" if not bad else f"{bad} of {len(STEPS)} steps need a pin"
    )
    return lines, bad == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("step", nargs="?", help=f"one of {', '.join(STEPS)}")
    parser.add_argument("run_id", nargs="?", help="the run to pin (not for feasibility)")
    parser.add_argument("--trial", metavar="NCT", help="the trial to open with the run")
    parser.add_argument("--remove", metavar="STEP", help="unpin this step")
    args = parser.parse_args(argv)
    if args.remove and (args.step or args.trial):
        parser.error("--remove takes only the step")

    init_db()
    try:
        if args.remove:
            step = parse_step(args.remove)
            print(f"{step}: removed" if store.delete_guide_pin(step) else f"{step}: not pinned")
            return 0
        if args.step is None:
            if args.trial:
                parser.error("--trial needs a step")
            lines, complete = report(store.list_guide_pins())
            print("\n".join(lines))
            return 0 if complete else 1
        pin = resolve_pin(parse_step(args.step), args.run_id, args.trial)
    except PinRefused as exc:
        print(f"guide-pin: {exc}", file=sys.stderr)
        return 2
    store.upsert_guide_pin(pin.step, pin.run_id, pin.nct_id)
    print(f"{pin.step}: pinned run {pin.run_id or '-'} trial {pin.nct_id or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
