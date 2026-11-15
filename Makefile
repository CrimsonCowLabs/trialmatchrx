.PHONY: install dev api web check check-api check-web types seed cohort eval compile-fixtures

API_PORT ?= 8000
WEB_PORT ?= 3000

install:
	cd api && uv sync
	cd web && pnpm install

# api on :8000 (uvicorn --reload) + web on :3000; Ctrl-C stops both.
dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd api && uv run uvicorn app.main:app --reload --port $(API_PORT)) & \
	(cd web && pnpm dev --port $(WEB_PORT)) & \
	wait

api:
	cd api && uv run uvicorn app.main:app --reload --port $(API_PORT)

web:
	cd web && pnpm dev --port $(WEB_PORT)

check: check-api check-web

check-api:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app/ && uv run pytest -q

check-web:
	cd web && pnpm typecheck && pnpm lint && pnpm test

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
# `ARGS=--bm25-only` skips it.
eval:
	cd api && uv run python -m scripts.run_eval $(ARGS)

# Compile the 10 fixture trials and print the compile rate. Real Sonnet needs ANTHROPIC_API_KEY;
# `make compile-fixtures ARGS=--fixtures` replays the saved (hand-authored) LLM outputs instead.
compile-fixtures:
	cd api && uv run python -m scripts.compile_fixtures $(ARGS)
