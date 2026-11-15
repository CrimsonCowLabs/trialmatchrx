"""POST /api/match and POST /api/closer: start a background run, return its id."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.schemas import CloserRequest, MatchRequest, RunStarted
from app.stub_data import STUB_CRITERIA, STUB_NCT, STUB_PATIENT, stub_matches
from app.trace import store
from app.trace.recorder import TraceRecorder
from app.trace.runner import start_traced_run

router = APIRouter(prefix="/api", tags=["match"])


# HACK(demo): stub — five fake trace events, 300 ms apart, then a fixed result (M2).
async def stub_match(rec: TraceRecorder, req: MatchRequest) -> dict[str, Any]:
    delay = get_settings().stub_event_delay_s
    note_len = len(req.note or "")

    await asyncio.sleep(delay)
    rec.event(
        "parse_patient",
        "step",
        input={"note_chars": note_len},
        output={"facts": 4},
        note=f"Parsed {note_len} chars into 4 facts (stub)",
    )
    await asyncio.sleep(delay)
    rec.event(
        "search_trials",
        "tool",
        input={"condition": req.condition, "radius_mi": req.radius_mi},
        output={"nct_ids": [STUB_NCT]},
        note="1 recruiting trial near Sacramento (stub)",
    )
    await asyncio.sleep(delay)
    rec.event(
        f"compile_criteria:{STUB_NCT}",
        "llm",
        input={"nct": STUB_NCT},
        output={"criteria": len(STUB_CRITERIA)},
        model="stub",
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        cache_hit=True,
        note="Compiled criteria from cache (stub)",
    )
    await asyncio.sleep(delay)
    rule = rec.event(
        f"rule:{STUB_NCT}:inc-1",
        "rule",
        input={"field": "labs.egfr", "op": ">=", "value": 45},
        output={"outcome": "pass", "actual": 48},
        note="eGFR 48 >= 45 -> pass (stub)",
    )
    await asyncio.sleep(delay)
    rec.event("rank", "step", output={"likely": 1}, note="1 likely, 0 needs info (stub)")

    return {
        "patient": STUB_PATIENT.model_dump(mode="json"),
        "matches": [m.model_dump(mode="json") for m in stub_matches(rule.id)],
    }


@router.post("/match", response_model=RunStarted)
async def start_match(req: MatchRequest) -> RunStarted:
    if not req.note and not req.fhir_bundle:
        raise HTTPException(status_code=422, detail="provide note or fhir_bundle")

    async def work(rec: TraceRecorder) -> dict[str, Any]:
        return await stub_match(rec, req)

    # HACK(demo): stub — DEMO_MODE=replay is not implemented yet (M7); always runs the stub.
    return RunStarted(run_id=start_traced_run("match", req.model_dump(mode="json"), work))


# HACK(demo): stub — fake agent steps and canned output until the LangGraph agent (M6).
async def stub_closer(rec: TraceRecorder, req: CloserRequest) -> dict[str, Any]:
    delay = get_settings().stub_event_delay_s
    async with rec.step("closer_agent", "run", {"run_id": req.run_id, "nct_id": req.nct_id}) as s:
        await asyncio.sleep(delay)
        rec.event(
            "get_unknown_criteria",
            "tool",
            input={"run_id": req.run_id, "nct": req.nct_id},
            output={"criteria": ["exc-1"]},
            note="1 unknown criterion (stub)",
        )
        await asyncio.sleep(delay)
        s.output = {
            "followups": [{"criterion_id": "exc-1", "ask": "Any DKA in the last 6 months?"}],
            "coordinator_email": "Stub email.",
            "patient_summary": {"en": "Stub summary.", "es": "Resumen de prueba."},
        }
    return {"closer": s.output}


@router.post("/closer", response_model=RunStarted)
async def start_closer(req: CloserRequest) -> RunStarted:
    if store.get_run(req.run_id) is None:
        raise HTTPException(status_code=404, detail=f"run {req.run_id} not found")

    async def work(rec: TraceRecorder) -> dict[str, Any]:
        return await stub_closer(rec, req)  # HACK(demo): stub

    # HACK(demo): stub — DEMO_MODE=replay is not implemented yet (M7); always runs the stub.

    return RunStarted(run_id=start_traced_run("closer", req.model_dump(mode="json"), work))
