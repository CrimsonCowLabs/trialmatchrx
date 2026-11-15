# TrialMatch Rx

Screens a patient against recruiting T2D/CKD trials with a live, auditable agent trace. Spec: [SPEC.md](SPEC.md).

Needs uv, Python 3.12, Node 22 and pnpm.

1. `make install` installs api (uv) and web (pnpm) dependencies.
2. `cp .env.example .env` and set `ANTHROPIC_API_KEY` (not needed for the M0 stubs).
3. `make dev` starts the api on :8000 and the web app on :3000; open http://localhost:3000/match.
4. `make check` runs ruff, mypy, pytest and the web typecheck + lint; `make types` regenerates `web/lib/api-types.ts`.
