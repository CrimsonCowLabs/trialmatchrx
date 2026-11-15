# TrialMatch Rx — Project Spec & Claude Code Kickoff

2026-11-11 · @Aaron

## Overview

TrialMatch Rx screens a patient against recruiting trials on ClinicalTrials.gov, explaining each criterion with a quoted source, and runs the same logic in reverse to show trial designers which criteria shrink their eligible pool. Every step the agent takes is visible in a live trace panel.

**The three demo moments**

1. **Match:** paste a patient, watch the agent work in the trace panel, and get ranked trials with a met / not met / unknown verdict per criterion, each verdict citing two quotes: one from the trial, one from the patient.
2. **Feasibility:** pick one trial and see how many of 1,000 synthetic patients qualify, as a waterfall of criteria. Moving a slider (e.g. eGFR ≥ 60 to ≥ 45) updates the count instantly.
3. **Proof:** an eval page with precision and nDCG@10 against expert labels from the TREC Clinical Trials track.

**Disease area: type 2 diabetes with chronic kidney disease.** Synthea generates realistic diabetes, CKD and hypertension records with labs (HbA1c, eGFR, BMI, blood pressure), so the feasibility simulator has real numbers to work with. Its oncology data is thin. ClinicalTrials.gov also lists many recruiting T2D/CKD trials, with numeric criteria that compile cleanly.

**In scope:** one disease area, a Sacramento-centered radius search, English criteria, synthetic data only, and a closer agent (follow-up questions, coordinator email, patient summary in Spanish).

**Out of scope:** authentication, real PHI, EHR write-back, multi-disease coverage, deployment beyond one demo host, and mobile layout.

**Design principle:** the LLM is used where language is ambiguous; code handles everything else. Criteria are compiled once into structured predicates and evaluated deterministically, which makes the slider instant, the results reproducible, and the eval cheap.

**Open question:** the HackRx site lists Saturday, October 17, not November 15. Confirm the date and whether code written before the event is allowed.

## Architecture

The stack is a Next.js frontend talking to one FastAPI service. LangChain handles the LLM steps and SQLite stores everything. There is no queue, no Docker and no vector database: a hackathon needs one process you can restart in two seconds.

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | Next.js (App Router) + React, Tailwind, shadcn/ui, Recharts | You know it; shadcn gives clean tables and sliders fast |
| API types | `openapi-typescript` generated from FastAPI's `/openapi.json` | One source of truth; frontend and backend sessions can't drift |
| Backend | FastAPI, Python 3.12, `uv`, Pydantic v2, `httpx` | Async fan-out to ClinicalTrials.gov and the LLM |
| LLM layer | LangChain + `langchain-anthropic`, `with_structured_output(PydanticModel)` | Typed outputs; callbacks feed the trace |
| Agent | LangGraph `create_react_agent` for the closer step only | The only open-ended step; everything else is a fixed pipeline |
| Models | Sonnet for compile and judge, Haiku for patient parsing; set in `.env` | Cost and latency where quality matters less |
| Storage | SQLite via SQLModel (`app.db`) | Trials cache, compiled criteria, cohort, runs, traces, eval results |
| Streaming | Server-Sent Events (`sse-starlette`) | One-way trace events; simpler than WebSockets |
| Data | ClinicalTrials.gov API v2, Synthea FHIR bundles, TREC CT 2021 topics + qrels | All public, no keys except the LLM |
| Optional | LangSmith tracing via env flag | A second view of the same runs; the app's own trace stays primary |

**Repo layout**

```
trialmatch/
  CLAUDE.md                # conventions for Claude Code (see Claude Code setup)
  SPEC.md                  # this document, exported as markdown
  api/
    app/
      main.py              # FastAPI app, routers, CORS
      config.py            # pydantic-settings: models, keys, DEMO_MODE
      db.py                # SQLModel engine + tables
      schemas.py           # ALL shared Pydantic contracts (single file on purpose)
      trace/
        recorder.py        # TraceRecorder + LangChain callback handler
        bus.py             # per-run asyncio queue for SSE
      sources/
        ctgov.py           # ClinicalTrials.gov v2 client + cache
        synthea.py         # FHIR bundle -> PatientFacts (deterministic)
        trec.py            # topics + qrels loader
      pipeline/
        parse_patient.py   # note -> PatientFacts (LLM)
        compile_criteria.py# eligibility text -> list[Criterion] (LLM, cached)
        evaluate.py        # predicates vs facts (pure Python)
        judge.py           # LLM judge for criteria with no predicate
        verify.py          # quote verification guardrail
        rank.py
        match.py           # orchestrates one match run
        feasibility.py     # predicates x cohort -> waterfall
        closer_agent.py    # LangGraph agent + tools
      routers/             # match.py, runs.py, trials.py, feasibility.py, eval.py
    scripts/               # seed_trials.py, load_cohort.py, run_eval.py, record_demo.py
    tests/                 # pytest, fixtures/ holds saved API responses
    pyproject.toml
  web/
    app/                   # /, /match/[runId], /feasibility/[nct], /eval, /trials, /runs, /runs/[runId]
    components/            # TracePanel, VerdictTable, CriterionRow, Waterfall, ThresholdSlider
    lib/api.ts             # typed client from generated types
    lib/sse.ts             # EventSource hook
  data/                    # synthea/, trec/, fixtures/ (gitignored except fixtures)
```

## UI design

The visual reference for every page is the claude.ai design project [TrialMatch Rx](https://claude.ai/design/p/aac54ca0-c646-4de6-bfba-526f38573c10):

- `TrialMatch Rx.dc.html`: every page, desktop and 390px mobile frames.
- `TM Sidebar.dc.html`: the desktop navigation sidebar.
- `TM Tabbar.dc.html`: the mobile tab bar.

The design's sample values (patients, trials, counts) are illustrative only; pages show real API data. Its colours live once, as tokens, in `web/app/globals.css` (teal accent, verdict pass / fail / unknown, run status, match tier, trial status and trace-event-kind colours, exposed as Tailwind classes such as `text-verdict-pass` or `bg-tier-likely-bg`); components use the tokens, never raw hex. Type is Geist and Geist Mono. Shared building blocks live in `web/components`: `PageHeader` (breadcrumb, title, description, actions), `StatusPill` (run status), `TierChips` (likely / needs info / ineligible counts) and the `Card` surface. Every page renders at 390px wide with 16px side gutters and no horizontal page scroll; wide tables scroll inside their card.

## Agent transparency

Every LLM call, tool call, rule evaluation and guardrail check is written as a trace event, streamed to the UI as it happens, and kept in SQLite for replay. Each verdict on screen links to the event that produced it. It ships in milestone 0, before any feature, because retrofitting it later costs more.

**Trace model** (in `schemas.py`)

```python
class TraceEvent(BaseModel):
    id: str                      # uuid
    run_id: str
    parent_id: str | None        # nests steps: run > trial > criterion > llm call
    seq: int                     # monotonic per run, for ordering + replay
    kind: Literal["run", "step", "llm", "tool", "rule", "guardrail", "error"]
    name: str                    # "compile_criteria", "judge:NCT05...:inc-3", "search_trials"
    status: Literal["started", "ok", "failed", "skipped"]
    started_at: datetime
    ended_at: datetime | None
    input: dict | None           # prompt messages / tool args / rule + facts
    output: dict | None          # parsed output / tool result / rule result
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    cache_hit: bool = False
    note: str | None             # human-readable one-liner shown in the timeline
```

**How events get recorded**

- `TraceRecorder` exposes `async with rec.step(name, kind, input) as s:` and sets `s.output` / status on exit, including on exceptions.
- A LangChain `AsyncCallbackHandler` (`on_chat_model_start`, `on_llm_end`, `on_tool_start`, `on_tool_end`, `on_llm_error`) writes `llm` and `tool` events automatically. It's passed via `config={"callbacks": [handler], "metadata": {"run_id": ..., "parent_id": ...}}`, so no pipeline code forgets to log.
- Deterministic steps (rule evaluation, ranking, cache lookups) log through the recorder too. They aren't LLM calls, but they are decisions, and showing them is the point.
- Every event goes to SQLite and to a per-run `asyncio.Queue` in `bus.py`.

**Streaming:** `GET /api/runs/{run_id}/events` is SSE. It first sends stored events (so a refresh or late open catches up), then live ones, then a final `done` event. The frontend uses one `useRunEvents(runId)` hook.

**Trace panel UI** (right-hand drawer on every run page)

- A timeline tree grouped by trial and then criterion. Each row shows an icon for the kind, the name, its status, latency, tokens and cost.
- Clicking a row expands the exact prompt messages, raw model output, parsed output and any validation errors.
- A header strip with totals: LLM calls, tokens, cost in $, wall time, cache hits.
- Two-way linking: "Why?" on any verdict scrolls to its trace event, and selecting an event highlights the verdict it produced.
- An "Export JSON" button and a `/runs/[runId]` page that replays a finished run in order.

**Guardrail: quote verification** (`verify.py`)

Each verdict must carry `criterion_quote` (from the trial text) and `patient_evidence` (from the patient note or facts). After the judge returns, code checks both are present in their source, using whitespace- and case-normalized matching with a `rapidfuzz` ratio of at least 90. On failure, the verdict is downgraded to `unknown`, a `guardrail` event records what failed, and the UI shows a small "unverified quote" badge. Show the guardrail count in the demo: judges like seeing that the system catches itself.

## Pipelines

Seven pipelines, of which only the criteria compiler, the judge and the closer agent call an LLM in the hot path. Each is one module under `api/app/pipeline/`, with a pytest that runs on saved fixtures and makes no network calls.

**1. Patient parse** (`parse_patient.py`)

- Input: a free-text note, or a Synthea FHIR bundle.
- Note path: Haiku with `with_structured_output(PatientFacts)`, asked to quote the source span for every fact it extracts (`facts[].source_span`).
- FHIR path: deterministic code in `sources/synthea.py`. It maps Condition, Observation (LOINC: HbA1c 4548-4, eGFR 33914-3 / 62238-1, BMI 39156-5, BP 85354-9) and MedicationRequest into the same `PatientFacts`. No LLM.
- Output: `PatientFacts`, a fixed vocabulary of age, sex, conditions[], labs{name: value, unit, date}, meds[], vitals{}, pregnancy, smoking, location.

**2. Trial search** (`sources/ctgov.py`)

- `GET https://clinicaltrials.gov/api/v2/studies` with `query.cond`, `filter.overallStatus=RECRUITING`, `filter.geo=distance(38.5816,-121.4944,50mi)` (Sacramento), `pageSize=50`, and `fields` limited to identification, status, eligibility, contacts and locations.
- Cache raw JSON in SQLite keyed by NCT ID + `lastUpdatePostDate`. `seed_trials.py` pre-fetches about 150 T2D/CKD trials so the demo never depends on venue Wi-Fi.

**3. Criteria compiler** (`compile_criteria.py`): the core of the project

- Input: `eligibilityModule.eligibilityCriteria` (free text), `minimumAge`, `maximumAge`, `sex`.
- Sonnet splits the text into atomic criteria. Each gets `id`, `type` (inclusion / exclusion), `text` (a verbatim quote), `category`, and a `predicate` written only against `PatientFacts` fields, e.g. `{"field": "labs.egfr", "op": ">=", "value": 45, "unit": "mL/min/1.73m2"}`. If a criterion can't be expressed with those fields, `predicate` is null and `needs_judgment` is true.
- Age and sex come from the structured fields, not the LLM.
- Cached per NCT ID + hash of the criteria text: compile once, reuse everywhere (match, feasibility, eval).
- Target: about 60% of criteria compile to predicates in T2D/CKD trials. Log the actual rate on the eval page.

**4. Matcher** (`evaluate.py`, `judge.py`, `verify.py`, `rank.py`, `match.py`)

- For each criterion, run its predicate if it has one (pure Python, logged as a `rule` event). Otherwise Sonnet judges it against `PatientFacts` plus the original note and returns `outcome`, `criterion_quote`, `patient_evidence` and `rationale`.
- `outcome` is relative to eligibility, so UI icons never need inverting: `pass` means the patient is fine on this criterion (an inclusion is met, or an exclusion doesn't apply), `fail` means it disqualifies them, and `unknown` means the data is missing.
- A missing fact gives `unknown`, never `fail`.
- Then `verify.py` checks every quote (see Agent transparency).
- Ranking: tier first (Likely eligible = no fails and at most 2 unknowns; Needs info = no fails, more unknowns; Ineligible = any fail), then fewer unknowns, then distance.
- Concurrency: `asyncio.Semaphore(8)` across trials and criteria. Expect about 20 trials in under 30 seconds with a warm compile cache.

**5. Closer agent** (`closer_agent.py`), the only real agent

- LangGraph `create_react_agent`, Sonnet, `recursion_limit=8`.
- Tools: `get_match_result(run_id, nct)`, `get_unknown_criteria(run_id, nct)`, `get_trial_contacts(nct)`, `get_patient_facts(run_id)`.
- Final structured output: `CloserOutput` with `followups[]` (each ties an unknown criterion to the test or question that resolves it), `coordinator_email`, and `patient_summary` in English and Spanish at a 6th-grade reading level.
- Every thought, tool call and tool result streams into the trace panel. This is the "watch it think" moment.

**6. Feasibility simulator** (`feasibility.py`)

- Cohort: `java -jar synthea-with-dependencies.jar -p 1000 California Sacramento`, then `load_cohort.py` maps each bundle to `PatientFacts` and stores them in a `cohort` table. Add `-m diabetes` if the pool comes out too small.
- Request: an NCT ID plus `overrides` (a criterion ID mapped to a new value).
- Logic: load the cohort into a pandas DataFrame once at startup and apply predicates in criterion order. Output a waterfall of patients remaining after each criterion, plus a leave-one-out impact per criterion (how many patients would be added if that criterion were dropped).
- Criteria with no predicate are counted as "needs review" and shown on a separate bar, never silently passed.
- No LLM, and under 100 ms, so the slider calls the API on every change (debounced 150 ms).

**7. Eval harness** (`sources/trec.py`, `scripts/run_eval.py`)

- Data: TREC 2021 Clinical Trials topics (75 patient descriptions) and qrels, labeled 0 = not relevant, 1 = excluded, 2 = eligible.
- Sample 15 topics × 20 judged trials, stratified across labels, for about 300 trials. Fetch each by NCT from `/api/v2/studies/{nct}`. Note the caveat: some records changed after 2021, so drop trials whose eligibility text no longer exists.
- Run the matcher on each topic and score nDCG@10 and P@10 (label 2 = relevant), plus eligible-vs-excluded accuracy on labels 1 and 2. Run it on the same sample every time.
- Write results to an `eval_runs` table with git SHA and prompt version. The `/eval` page shows the latest score and the history, so prompt changes have a number attached.
- Report a baseline as well: BM25 over the trial text (`rank_bm25`). "We beat keyword search by X" is the claim judges remember.

## Data contracts and API

All contracts live in `api/app/schemas.py` and are frozen at the end of milestone 0. After that, parallel sessions can only change them through a PR that regenerates `web/lib/api-types.ts`.

```python
class Fact(BaseModel):
    value: str | float | bool
    unit: str | None = None
    date: date | None = None
    source_span: str | None = None     # verbatim text from the note, for verification

class PatientFacts(BaseModel):
    age: int | None; sex: Literal["female", "male"] | None
    conditions: list[Fact]             # value = condition name; SNOMED code optional
    labs: dict[str, Fact]              # keys: hba1c, egfr, uacr, ldl, potassium ...
    vitals: dict[str, Fact]            # bmi, sbp, dbp
    meds: list[Fact]                   # value = drug name; plus drug_class if known
    pregnant: bool | None; smoker: bool | None
    lat: float | None; lon: float | None
    place: str | None = None           # "Sacramento, CA": the note's verified place or the FHIR address

class Predicate(BaseModel):
    field: str                         # dotted path into PatientFacts
    op: Literal[">=", "<=", ">", "<", "==", "in", "has", "not_has"]
    value: float | str | list[str]
    unit: str | None = None

class Criterion(BaseModel):
    id: str                            # "inc-3", "exc-7"
    type: Literal["inclusion", "exclusion"]
    text: str                          # verbatim from the trial
    category: Literal["demographic", "diagnosis", "lab", "medication", "history", "procedure", "other"]
    predicate: Predicate | None
    needs_judgment: bool

class Verdict(BaseModel):
    criterion_id: str
    outcome: Literal["pass", "fail", "unknown"]
    method: Literal["rule", "llm"]
    criterion_quote: str
    patient_evidence: str | None
    rationale: str
    verified: bool
    trace_event_id: str                # powers the "Why?" link

Tier = Literal["likely", "needs_info", "ineligible"]

class TrialMatch(BaseModel):
    nct_id: str; title: str; phase: str | None; distance_mi: float | None
    tier: Tier
    verdicts: list[Verdict]
    counts: dict[str, int]             # pass / fail / unknown

class FeasibilityResult(BaseModel):
    nct_id: str; cohort_size: int
    waterfall: list[dict]              # {criterion_id, text, remaining, dropped}
    leave_one_out: list[dict]          # {criterion_id, added_if_removed}
    needs_review: int

class TrialListItem(BaseModel):        # one row of /trials
    nct_id: str; title: str; phase: str | None; overall_status: str | None
    compiled: bool; criteria_count: int

class TierCounts(BaseModel):
    likely: int = 0; needs_info: int = 0; ineligible: int = 0

class RunListItem(BaseModel):          # one row of /runs; from the run row only, no totals
    run_id: str; kind: RunKind; status: RunStatus
    created_at: datetime; ended_at: datetime | None
    patient_label: str | None          # e.g. "58 F", once the run has finished
    tier_counts: TierCounts

class RunStats(BaseModel):             # the match form's duration / cost hint
    runs: int                          # recent finished (done) match runs summarised
    wall_time_min_s: float | None; wall_time_max_s: float | None
    cost_usd_median: float | None      # None everywhere when runs == 0
```

| Method | Path | Body / params | Returns |
| --- | --- | --- | --- |
| POST | `/api/match` | `{note?: str, fhir_bundle?: dict, condition: str, radius_mi: int = 50}` | `{run_id}`; work continues in a background task |
| GET | `/api/runs` | `?kind: RunKind = match`, `?limit: int = 50` (max 200) | `list[RunListItem]`, newest first; read-only, not traced |
| GET | `/api/runs/stats` | `?limit: int = 20` (max 200) | `RunStats` over the newest `limit` finished match runs: wall-time range and median cost from stored runs; read-only, not traced |
| GET | `/api/runs/{run_id}/events` | SSE | `TraceEvent` stream, then `done` |
| GET | `/api/runs/{run_id}` |  | `RunSummary`: `{status, patient: PatientFacts, matches: list[TrialMatch], totals, closer, patient_label, condition, max_unknowns_for_likely}`; `patient_label` is as on `RunListItem`, `condition` is the match request's (None for a closer run), `max_unknowns_for_likely` the tier rule's threshold |
| GET | `/api/runs/{run_id}/trace` |  | `list[TraceEvent]` (export / replay) |
| GET | `/api/trials` | `?q: str` (substring of NCT ID or title) | `list[TrialListItem]` from the trials cache, by NCT ID; no network, not traced |
| GET | `/api/trials/{nct}` |  | trial summary + compiled `list[Criterion]` |
| POST | `/api/trials/{nct}/compile` | `{force: bool}` | `list[Criterion]`, traced |
| POST | `/api/feasibility/{nct}` | `{overrides: {criterion_id: value}}` | `FeasibilityResult` |
| POST | `/api/closer` | `{run_id, nct_id}` | `{run_id}` of a new agent run, streamed like a match |
| GET | `/api/eval/latest` |  | metrics, baseline, compile rate, history |
| GET | `/api/health` |  | `{ok, demo_mode, model_ids}` |

**`DEMO_MODE=replay`:** `/api/match` and `/api/closer` replay a recorded run from `data/fixtures/runs/*.json`, re-emitting events with their original timing (capped at 0.2 s gaps). It's the same UI and the same trace. Record the fixtures with `scripts/record_demo.py` the night before.

## Milestones and timeline

M0 lands on main first, then three git worktrees build in parallel and merge on Saturday for the closer agent and demo hardening. If pre-built code isn't allowed, use this week for prompts, fixtures, the cohort and the TREC sample, then run M0 to M3 on event day before anything else.

_[embedded: build plan · 8 milestones, 3 parallel worktrees]_

Each worktree owns its own folders, so sessions never edit the same files: wt-pipeline owns `api/app/pipeline` and `sources/ctgov.py`, wt-web owns `web/`, wt-data owns `sources/synthea.py`, `sources/trec.py`, `feasibility.py` and `scripts/`.

```bash
git worktree add ../tm-pipeline -b feat/pipeline
git worktree add ../tm-web -b feat/web
git worktree add ../tm-data -b feat/data
# one Claude Code session per folder; merge to main daily after make check
```

**Acceptance per milestone** (paste into each session's prompt)

1. **M0:** `make check` passes; a stub match streams 5 trace events into the UI.
2. **M1:** `make seed` caches at least 100 recruiting T2D/CKD trials near Sacramento; compiling 10 fixture trials gives valid `Criterion` lists, and the compile rate is printed.
3. **M2:** a demo-patient run returns ranked `TrialMatch` results in under 30 s with a warm cache; every verdict has a `trace_event_id`; a test proves a fabricated quote is downgraded to `unknown`.
4. **M3:** the match page shows tiers, criterion rows with icons, "Why?" linking to the trace drawer, a live totals strip, and JSON export.
5. **M4:** `make eval` prints nDCG@10, P@10 and accuracy for the matcher and BM25 on the fixed sample, writes `eval_runs`, and `/eval` renders it.
6. **M5:** 1,000-patient cohort loaded; `/api/feasibility/{nct}` returns in under 100 ms; the slider updates the waterfall live.
7. **M6:** the closer agent produces follow-ups, an email and a Spanish summary, with every tool call visible in the trace.
8. **M7:** with Wi-Fi off and `DEMO_MODE=replay`, the full 3-minute demo runs twice in a row without errors.

## Claude Code setup

For visibility into Claude Code's own work, use the same rules as the app: plan before code, one small commit per task, and an append-only log. Export this doc to markdown as `SPEC.md`, add the `CLAUDE.md` below, then paste the kickoff prompt.

**`CLAUDE.md`** (repo root)

```markdown
# TrialMatch Rx — working rules

Spec: SPEC.md is the source of truth. If something in it is wrong or missing, stop and ask; don't improvise.

## How you work
- Plan first. For every milestone, write the plan (files to touch, tests to add, open questions) and wait for my OK.
- One task = one commit, conventional message (feat:, fix:, test:, chore:). Never batch unrelated changes.
- Log every decision the spec didn't make under "Decisions" in the commit message, one line each.
- Never mark a task done with failing checks. Run `make check` (ruff, mypy app/, pytest, web typecheck + lint) before each commit.
- No new dependencies without a one-line justification in the commit message.
- Never hide a shortcut. Stubs, hardcoded values and TODOs get a `# HACK(demo):` comment.

## Code rules
- All shared types in api/app/schemas.py. Change a schema -> run `make types` to regenerate web/lib/api-types.ts in the same commit.
- Every LLM call goes through LangChain with the trace callback attached, and every deterministic decision step uses TraceRecorder.step(). No untraced calls.
- Prompts live in api/app/prompts/*.md with a `version:` header; never inline.
- Tests use fixtures in api/tests/fixtures; no network in pytest. Mark live tests @pytest.mark.live.
- Synthetic data only. Never add real patient data.

## Commands
- make dev      # api on :8045 (uvicorn --reload) + web on :3045
- make check    # all linters + tests
- make types    # regenerate TS types from OpenAPI
- make seed     # fetch trials, load cohort
- make eval     # run TREC eval, write eval_runs
```

**Kickoff prompt** (session 1, run in plan mode)

```text
Read SPEC.md and CLAUDE.md fully before doing anything.

We are building TrialMatch Rx for a one-day hackathon. Your job right now is Milestone 0 only:
the skeleton and the contracts that let parallel sessions start safely.

Milestone 0 deliverables:
1. Monorepo per the "Repo layout" in SPEC.md: api/ (FastAPI, uv, Python 3.12) and web/ (Next.js App Router, TypeScript, Tailwind, shadcn/ui).
2. api/app/schemas.py with every contract from "Data contracts and API", exactly as specified.
3. All routers from the API table, returning typed stub data that matches the schemas (mark each # HACK(demo): stub).
4. trace/recorder.py + trace/bus.py + the SSE endpoint working end to end: a stub /api/match run that emits 5 fake TraceEvents, 300 ms apart.
5. web/: a /match page that POSTs a note, opens the SSE stream, and renders events in a basic TracePanel. Ugly is fine.
6. Makefile with dev, check, types, seed (no-op for now), eval (no-op for now).
7. README with setup in under 10 lines.

Acceptance: `make check` passes; `make dev`, paste text on /match, and see 5 events stream in.

Process:
- First reply: your plan as a checklist, the exact package list, and any questions about SPEC.md. Then stop and wait for my OK.
- After my OK: work task by task, commit each.
- Do NOT start Milestone 1. When M0 is done, summarize what exists, what is stubbed, and what you'd flag for review.
```

**Prompt for each later session** (copy it and swap in the milestone)

```text
Read SPEC.md and CLAUDE.md. You are in worktree <name> on branch <branch>.
Your scope is Milestone <N>: <title> from SPEC.md, and only the files that milestone owns.
Do not edit schemas.py; if you need a contract change, stop and tell me exactly what and why.
First reply: plan as a checklist + questions, then wait. Then task by task: commit, log, `make check`.
Finish with: what works, what is stubbed (# HACK), test results, and the demo command to see it.
```

**Getting the most out of a big token budget**

- Spend tokens on verification, not volume. After each milestone, start a fresh session: "Review the diff of branch X against SPEC.md. List deviations, untraced LLM calls, and untested paths. Don't fix anything."
- Have one session iterate on prompts against `make eval`: "Improve prompts/judge.md. Run make eval after each change, keep a table of version vs. nDCG@10, and stop after 5 iterations or no gain."
- Keep sessions short and scoped. A fresh session per milestone beats one long one that loses the thread.

## Demo script, risks and fallbacks

The pitch is 3 minutes. Open with the number, show the agent working, and end on the slider.

1. **0:00 – Hook (20 s).** "Most trials miss their enrollment targets, and screening one patient against one trial takes a coordinator about an hour. On expert-labeled TREC cases, our matcher scores nDCG@10 of X, versus Y for keyword search."
2. **0:20 – Match (60 s).** Paste the demo patient: 61M, T2D, HbA1c 8.4%, eGFR 48, on metformin, Sacramento. The trace panel fills live. Open the top trial, click "Why?" on one ❌, and show both quotes and the exact prompt.
3. **1:20 – Closer (35 s).** Click "Next steps." The agent calls its tools in the trace and produces follow-up tests for the ❓ criteria, a coordinator email, and the Spanish patient summary.
4. **1:55 – Feasibility (45 s).** Flip to the trial-designer view: 1,000 synthetic patients, and the waterfall shows eGFR ≥ 60 removes the most. Drag the slider to 45 and watch the eligible count jump.
5. **2:40 – Close (20 s).** Who pays (cancer centers, CROs, sponsors), what's next (SMART on FHIR launch), and that it was built in a day with every agent step auditable.

| Risk | Likelihood | Fallback |
| --- | --- | --- |
| Venue Wi-Fi fails or LLM latency spikes | High | `DEMO_MODE=replay` with recorded runs; trials and cohort already in SQLite |
| Judge prompt returns malformed JSON | Medium | `with_structured_output` + one retry; on second failure the criterion becomes `unknown` with an `error` event, visible in the trace |
| Compile rate is low, so feasibility shows a big "needs review" bar | Medium | Pick demo trials with high compile rates; say so openly, it shows honesty |
| Synthea cohort has too few T2D/CKD patients | Medium | Generate with `-m diabetes`, or bump to `-p 3000` |
| TREC records changed since 2021 | Medium | Drop changed trials and report the sample size on the eval page |
| Eval score is unimpressive | Medium | Lead with the BM25 comparison and accuracy on eligible vs excluded; show the prompt-iteration table as progress |
| Pre-built code not allowed | Unknown | This week: prompts, fixtures, Synthea cohort, TREC sample, demo script. Event day: M0 to M3 first, then add features in order of impact |
| Scope creep on the day | High | Hard stop on features 1 hour before judging; rehearse twice |
