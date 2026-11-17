.PHONY: install dev api web check check-api check-web check-scripts types seed cohort eval eval-offline \
	eval-smoke compile-fixtures record-demo guide-pin dev-user reset-link users disable-user admin invite access-requests deploy

API_PORT ?= 8045
WEB_PORT ?= 3045

install:
	cd api && uv sync
	cd web && pnpm install

# The dev API is plain http://localhost, so its session cookie can't be Secure (on by default).
DEV_API_ENV := SESSION_COOKIE_SECURE=false

# api on :8045 (uvicorn --reload) + web on :3045; Ctrl-C stops both.
dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd api && $(DEV_API_ENV) uv run uvicorn app.main:app --reload --port $(API_PORT)) & \
	(cd web && pnpm dev --port $(WEB_PORT)) & \
	wait

api:
	cd api && $(DEV_API_ENV) uv run uvicorn app.main:app --reload --port $(API_PORT)

web:
	cd web && pnpm dev --port $(WEB_PORT)

check: check-api check-web check-scripts

check-api:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app/ && uv run pytest -q

check-web:
	cd web && pnpm typecheck && pnpm lint && pnpm test

# The deploy scripts' suites: stubs only, no Docker, no network, no box.
check-scripts:
	@for t in scripts/tests/test-*.sh; do \
		out="$$(bash "$$t")" || { printf '%s\n' "$$out"; exit 1; }; \
		printf '%s: %s\n' "$$t" "$$(printf '%s\n' "$$out" | tail -1)"; \
	done

# Build and ship the latest origin/main to ccl-vps, whatever branch is checked out here:
# scripts/deploy-main.sh checks it out in a temporary worktree and runs that commit's
# scripts/deploy.sh. `make deploy ARGS=--dry-run` says what it would do, and stops.
deploy:
	./scripts/deploy-main.sh $(ARGS)

# Regenerate web/lib/api-types.ts from FastAPI's OpenAPI (no server needed).
types:
	cd api && uv run python -m scripts.export_openapi openapi.json
	cd web && pnpm exec openapi-typescript ../api/openapi.json -o lib/api-types.ts

# Pre-fetch T2D/CKD trials into the SQLite cache (network), then load the cohort.
seed:
	cd api && uv run python -m scripts.seed_trials
	$(MAKE) cohort

# 1,000 Synthea patients near Sacramento into the cohort table. Needs Java 11+; downloads the
# pinned Synthea jar once and generates only when data/synthea/output/fhir doesn't exist yet.
# Ages 40-85 (adult T2D/CKD trials) for a meaningful T2D/CKD pool. Pinned release, seeds and
# reference date, so it reproduces; delete data/synthea/output to regenerate.
SYNTHEA_DIR := data/synthea
SYNTHEA_VERSION := v4.0.0
SYNTHEA_JAR := synthea-with-dependencies-$(SYNTHEA_VERSION).jar
SYNTHEA_DATE := 2026-11-12
SYNTHEA_ARGS ?= -s 42 -cs 42 -p 1000 -a 40-85 -r $(subst -,,$(SYNTHEA_DATE))

cohort:
	@mkdir -p $(SYNTHEA_DIR)
	@test -f $(SYNTHEA_DIR)/$(SYNTHEA_JAR) || curl -fL -o $(SYNTHEA_DIR)/$(SYNTHEA_JAR) \
		https://github.com/synthetichealth/synthea/releases/download/$(SYNTHEA_VERSION)/synthea-with-dependencies.jar
	@test -d $(SYNTHEA_DIR)/output/fhir || (cd $(SYNTHEA_DIR) && \
		java -jar $(SYNTHEA_JAR) $(SYNTHEA_ARGS) \
		--exporter.baseDirectory=./output/ --exporter.years_of_history=5 \
		--exporter.fhir.export=true --exporter.hospital.fhir.export=false \
		--exporter.practitioner.fhir.export=false --exporter.csv.export=false \
		--generate.only_alive_patients=true California Sacramento)
	cd api && uv run python -m scripts.load_cohort --as-of $(SYNTHEA_DATE)

# Matcher + BM25 on the fixed TREC sample -> eval_runs. Builds data/fixtures/trec/sample.json on
# first run (network); `make eval ARGS=--rebuild` redraws and refetches it. The matcher needs
# ANTHROPIC_API_KEY (skipped without it) and replays cached LLM answers on a re-run;
# `ARGS=--bm25-only` skips it. `ARGS="--topics N"` scores both on only the first N topics (a cheap
# live check): reported as partial, never written to eval_runs, its answers still cached.
# `ARGS=--offline` scores the matcher from the caches only (no API calls, no key; misses are
# counted per step, and an incomplete run records nothing and exits 1). `ARGS=--fail-fast` stops
# at the first model failure (or, with --offline, cache miss), records nothing and exits 1.
eval:
	cd api && uv run python -m scripts.run_eval $(ARGS)

# Shortcuts for the usual loop: `make eval-smoke` after a pipeline change (one topic live, stops
# at the first failure, never recorded; needs ANTHROPIC_API_KEY, spends a few tokens), then
# `make eval-offline` to re-score for free (no LLM calls, no tokens; records only a complete
# replay). `make eval` is the run that fills the caches and records a score. Both take ARGS too.
eval-offline:
	cd api && uv run python -m scripts.run_eval --offline $(ARGS)

eval-smoke:
	cd api && uv run python -m scripts.run_eval --topics 1 --fail-fast $(ARGS)

# Compile the 10 fixture trials and print the compile rate. Real Sonnet needs ANTHROPIC_API_KEY;
# `make compile-fixtures ARGS=--fixtures` replays the saved (hand-authored) LLM outputs instead.
compile-fixtures:
	cd api && uv run python -m scripts.compile_fixtures $(ARGS)

# Record each demo patient's match run and the closer run on its top trial into
# data/fixtures/runs/ for DEMO_MODE=replay. Needs ANTHROPIC_API_KEY and `make seed` first.
# `ARGS="--patient als"` records one patient (repeatable); `ARGS="--patient t2d --nct NCT..."`
# picks the closer's trial; `ARGS="--from-runs MATCH_ID CLOSER_ID"` saves two finished runs
# from app.db instead (offline, e.g. a rehearsal done in the UI).
record-demo:
	cd api && uv run python -m scripts.record_demo $(ARGS)

# Pin the first-time guide's steps to recorded runs (guide_pins; GET /api/guide only reads it).
# `ARGS="als RUN_ID"` (als / ipf / ipf_flip: a done match run, `--trial NCT` one of its matches),
# `ARGS="pah RUN_ID"` (a done closer run; its trial comes from the run), `ARGS="feasibility
# --trial NCT"` (a cached trial, no run), `ARGS="--remove STEP"`. No ARGS lists every step and
# exits 1 unless all are pinned to runs that still exist. In prod there's no make: see README.
guide-pin:
	cd api && uv run python -m scripts.guide_pin $(ARGS)

# Create (or reset) the local sign-in account dev@localhost and print its password. Refuses
# unless DATABASE_URL is a SQLite file inside api/ (the default api/app.db), so never in prod.
dev-user:
	cd api && uv run python -m scripts.dev_user

# Print a one-time password-reset link (1 hour) for EMAIL; send it yourself, there's no email.
# Using it sets a new password and ends all of that account's sessions. Refuses an unknown or
# disabled account. In prod there's no make: see api/scripts/reset_link.py.
reset-link:
	@test -n "$(EMAIL)" || { echo "usage: make reset-link EMAIL=someone@example.com" >&2; exit 2; }
	cd api && uv run python -m scripts.reset_link "$(EMAIL)"
# List every account: email, created date, last sign-in, passkeys, password set, disabled, admin.
# In prod there's no make: see README.
users:
	cd api && uv run python -m scripts.users

# List request-access submissions from the form on `/`, newest first: received (UTC), name,
# email, organization, role, and the message below. In prod there's no make: see README.
access-requests:
	cd api && uv run python -m scripts.access_requests

# End EMAIL's sessions and block sign-in; the row stays so `created_by` still resolves.
# Unknown email exits 2; an already-disabled account says so. In prod: see README.
disable-user:
	@test -n "$(EMAIL)" || { echo "usage: make disable-user EMAIL=..." >&2; exit 2; }
	cd api && uv run python -m scripts.disable_user "$(EMAIL)"

# Make EMAIL's existing account an admin (SPEC.md "Admin"; the only way to set is_admin).
# Unknown email exits 2; an account that's already an admin says so. In prod: see README.
admin:
	@test -n "$(EMAIL)" || { echo "usage: make admin EMAIL=..." >&2; exit 2; }
	cd api && uv run python -m scripts.admin "$(EMAIL)"

# Print a one-time invite link for EMAIL (7 days; SPEC.md "Marketing and accounts"). Refuses an
# email that already has an account. The link's origin is APP_URL (default
# http://localhost:3045). No email is sent: send the link yourself. In prod there's no make:
# see README.
invite:
	@test -n "$(EMAIL)" || { echo "usage: make invite EMAIL=someone@example.com" >&2; exit 2; }
	cd api && uv run python -m scripts.invite "$(EMAIL)"
