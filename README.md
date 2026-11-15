# TrialMatch Rx

Screens a patient against recruiting T2D/CKD trials with a live, auditable agent trace. Spec: [SPEC.md](SPEC.md).

Needs uv, Python 3.12, Node 22 and pnpm.

1. `make install` installs api (uv) and web (pnpm) dependencies.
2. `cp .env.example .env` and set `ANTHROPIC_API_KEY` (not needed for the M0 stubs).
3. `make dev` starts the api on :8045 and the web app on :3045; open http://localhost:3045/match.
4. `make check` runs ruff, mypy, pytest and the web typecheck + lint; `make types` regenerates `web/lib/api-types.ts`.
5. Offline demo: `make seed`, then `make record-demo` (needs `ANTHROPIC_API_KEY`) records the demo patient's match and closer runs into `data/fixtures/runs/`. Start with `DEMO_MODE=replay` in `.env` and `/api/match` and `/api/closer` replay them with their original timing (gaps capped at 0.2 s), no network or key needed. `GET /api/health` shows `demo_mode` and is `ok: false` in replay mode until both runs are recorded.
