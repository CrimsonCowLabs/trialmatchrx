.PHONY: install dev api web check check-api check-web types seed eval

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

seed:
	@echo "make seed: no-op until M1 (seed_trials.py) and M5 (load_cohort.py)"  # HACK(demo): stub

eval:
	@echo "make eval: no-op until M4 (run_eval.py)"  # HACK(demo): stub
