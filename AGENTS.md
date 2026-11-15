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
- make dev           # api on :8045 (uvicorn --reload) + web on :3045
- make check         # all linters + tests
- make types         # regenerate TS types from OpenAPI
- make seed          # fetch trials, load cohort
- make eval          # run TREC eval, write eval_runs; run it only when you want a recorded score
- make eval-smoke    # 1 topic live, stops at the first failure, never recorded; run after a pipeline change
- make eval-offline  # re-score from the caches for free (no LLM calls); records only a fully cached run

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues on `crimsoncowlabs/trialmatchrx`, using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root, created only when needed. See `docs/agents/domain.md`.
