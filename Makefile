.PHONY: install dev api web check check-api check-web types seed eval compile-fixtures

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
	cd web && pnpm typecheck && pnpm lint

# Regenerate web/lib/api-types.ts from FastAPI's OpenAPI (no server needed).
types:
	cd api && uv run python -m scripts.export_openapi openapi.json
	cd web && pnpm exec openapi-typescript ../api/openapi.json -o lib/api-types.ts

# Pre-fetch T2D/CKD trials into the SQLite cache (network). Cohort loading lands in M5.
seed:
	cd api && uv run python -m scripts.seed_trials
	@echo "make seed: cohort (load_cohort.py) not loaded until M5"  # HACK(demo): stub

eval:
	@echo "make eval: no-op until M4 (run_eval.py)"  # HACK(demo): stub

# Compile the 10 fixture trials and print the compile rate. Real Sonnet needs ANTHROPIC_API_KEY;
# `make compile-fixtures ARGS=--fixtures` replays the saved (hand-authored) LLM outputs instead.
compile-fixtures:
	cd api && uv run python -m scripts.compile_fixtures $(ARGS)
