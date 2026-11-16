"""scripts/guide_pin.py: `make guide-pin` pins, replaces, removes and lists the first-time
guide's runs. Against the per-test SQLite file (conftest), no network."""

from typing import Any

import pytest

from app.schemas import GuidePin, RunKind, RunStatus
from app.sources import ctgov
from app.trace import store
from scripts.guide_pin import main

ALS_TRIAL = "NCT05000001"
OTHER_TRIAL = "NCT05000002"
CACHED_TRIAL = "NCT06000001"


def make_run(
    kind: RunKind,
    *,
    status: RunStatus = "done",
    request: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> str:
    """A run in the runs table, finished with `status` (left running if that's the status)."""
    run_id = store.create_run(kind, request or {})
    if status != "running":
        store.finish_run(run_id, status, result=result)
    return run_id


def match_run(*ncts: str, status: RunStatus = "done") -> str:
    return make_run("match", status=status, result={"matches": [{"nct_id": n} for n in ncts]})


def closer_run(nct: str, status: RunStatus = "done") -> str:
    return make_run("closer", status=status, request={"run_id": match_run(nct), "nct_id": nct})


def cache_trial(nct: str) -> None:
    ctgov.cache_study(
        {
            "protocolSection": {
                "identificationModule": {"nctId": nct},
                "statusModule": {"lastUpdatePostDateStruct": {"date": "2026-01-01"}},
            }
        }
    )


def pins() -> dict[str, GuidePin]:
    return {p.step: p for p in store.list_guide_pins()}


def refused(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    """Run the script expecting a refusal: non-zero exit, nothing pinned. Its stderr."""
    before = pins()
    assert main(argv) != 0
    assert pins() == before
    return capsys.readouterr().err


# --- create, replace, remove -------------------------------------------------------------


def test_pins_a_match_step_to_a_finished_match_run() -> None:
    run_id = match_run(ALS_TRIAL)

    assert main(["als", run_id]) == 0

    assert pins()["als"] == GuidePin(step="als", run_id=run_id, nct_id=None, run_exists=True)


def test_trial_in_the_runs_matches_is_pinned_with_it() -> None:
    run_id = match_run(ALS_TRIAL, OTHER_TRIAL)

    assert main(["ipf", run_id, "--trial", OTHER_TRIAL]) == 0

    assert (pins()["ipf"].run_id, pins()["ipf"].nct_id) == (run_id, OTHER_TRIAL)


def test_pinning_again_replaces_the_pin() -> None:
    before, after = match_run(ALS_TRIAL), match_run(OTHER_TRIAL)
    main(["ipf_flip", before, "--trial", ALS_TRIAL])

    assert main(["ipf_flip", after]) == 0

    assert (pins()["ipf_flip"].run_id, pins()["ipf_flip"].nct_id) == (after, None)


def test_remove_unpins_a_step(capsys: pytest.CaptureFixture[str]) -> None:
    main(["als", match_run(ALS_TRIAL)])

    assert main(["--remove", "als"]) == 0

    assert "als" not in pins()
    assert "removed" in capsys.readouterr().out


def test_removing_an_unpinned_step_says_not_pinned(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--remove", "pah"]) == 0

    assert "not pinned" in capsys.readouterr().out


# --- refusals ----------------------------------------------------------------------------


def test_unknown_step_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    err = refused(["eval", match_run(ALS_TRIAL)], capsys)

    assert "unknown step 'eval'" in err
    assert "als, ipf, ipf_flip, pah, feasibility" in err


def test_unknown_step_to_remove_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert "unknown step 'nope'" in refused(["--remove", "nope"], capsys)


def test_missing_run_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert "no run 'no-such-run'" in refused(["als", "no-such-run"], capsys)


def test_a_step_needs_a_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert "als needs a run_id" in refused(["als"], capsys)


def test_wrong_run_kind_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    closer = closer_run(ALS_TRIAL)
    err = refused(["als", closer], capsys)
    assert f"run {closer} is a closer run; als needs a match run" in err

    match = match_run(ALS_TRIAL)
    assert f"run {match} is a match run; pah needs a closer run" in refused(["pah", match], capsys)


@pytest.mark.parametrize("status", ["running", "failed"])
def test_a_run_that_is_not_done_is_refused(
    status: RunStatus, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = match_run(ALS_TRIAL, status=status)

    assert f"run {run_id} is {status}, not done" in refused(["als", run_id], capsys)


def test_trial_not_in_the_runs_matches_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    run_id = match_run(ALS_TRIAL, OTHER_TRIAL)

    err = refused(["ipf", run_id, "--trial", "NCT09999999"], capsys)

    assert f"NCT09999999 is not among run {run_id}'s matches" in err
    assert f"{ALS_TRIAL}, {OTHER_TRIAL}" in err


# --- pah: the closer run --------------------------------------------------------------------


def test_pah_takes_its_trial_from_the_closer_request() -> None:
    run_id = closer_run(OTHER_TRIAL)

    assert main(["pah", run_id]) == 0

    assert (pins()["pah"].run_id, pins()["pah"].nct_id) == (run_id, OTHER_TRIAL)


def test_pah_refuses_trial(capsys: pytest.CaptureFixture[str]) -> None:
    err = refused(["pah", closer_run(OTHER_TRIAL), "--trial", OTHER_TRIAL], capsys)

    assert "pah takes its trial from the closer run; drop --trial" in err


# --- feasibility: a trial, no run ------------------------------------------------------------


def test_feasibility_pins_a_cached_trial() -> None:
    cache_trial(CACHED_TRIAL)

    assert main(["feasibility", "--trial", CACHED_TRIAL]) == 0

    assert pins()["feasibility"] == GuidePin(
        step="feasibility", run_id=None, nct_id=CACHED_TRIAL, run_exists=False
    )


def test_feasibility_needs_trial(capsys: pytest.CaptureFixture[str]) -> None:
    assert "feasibility needs --trial" in refused(["feasibility"], capsys)


def test_feasibility_refuses_a_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    cache_trial(CACHED_TRIAL)

    err = refused(["feasibility", match_run(CACHED_TRIAL), "--trial", CACHED_TRIAL], capsys)

    assert "feasibility takes no run_id" in err


def test_feasibility_refuses_a_trial_not_in_the_cache(capsys: pytest.CaptureFixture[str]) -> None:
    err = refused(["feasibility", "--trial", CACHED_TRIAL], capsys)

    assert f"{CACHED_TRIAL} is not in the trials cache" in err


# --- list mode -------------------------------------------------------------------------------


def pin_everything() -> dict[str, str]:
    ids = {
        "als": match_run(ALS_TRIAL),
        "ipf": match_run(ALS_TRIAL),
        "ipf_flip": match_run(ALS_TRIAL),
        "pah": closer_run(OTHER_TRIAL),
    }
    assert main(["als", ids["als"]]) == 0
    assert main(["ipf", ids["ipf"], "--trial", ALS_TRIAL]) == 0
    assert main(["ipf_flip", ids["ipf_flip"]]) == 0
    assert main(["pah", ids["pah"]]) == 0
    cache_trial(CACHED_TRIAL)
    assert main(["feasibility", "--trial", CACHED_TRIAL]) == 0
    return ids


def test_list_with_every_step_pinned_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    ids = pin_everything()
    capsys.readouterr()

    assert main([]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:2] for line in lines[:5]] == [
        ["als", "pinned"],
        ["ipf", "pinned"],
        ["ipf_flip", "pinned"],
        ["pah", "pinned"],
        ["feasibility", "pinned"],
    ]
    assert ids["ipf"] in lines[1] and ALS_TRIAL in lines[1]
    assert ids["pah"] in lines[3] and OTHER_TRIAL in lines[3]
    assert CACHED_TRIAL in lines[4]
    assert lines[5] == "all 5 steps pinned"


def test_list_with_a_step_missing_or_its_run_gone_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = match_run(ALS_TRIAL)
    main(["als", run_id])
    store.upsert_guide_pin("ipf", "deleted-run", None)  # a pin whose run has since gone
    capsys.readouterr()

    assert main([]) == 1

    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:2] for line in lines[:5]] == [
        ["als", "pinned"],
        ["ipf", "RUN"],
        ["ipf_flip", "MISSING"],
        ["pah", "MISSING"],
        ["feasibility", "MISSING"],
    ]
    assert "RUN GONE" in lines[1] and "deleted-run" in lines[1]
    assert run_id in lines[0]
    assert lines[5] == "4 of 5 steps need a pin"


def test_list_with_nothing_pinned_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 1

    assert capsys.readouterr().out.count("MISSING") == 5
