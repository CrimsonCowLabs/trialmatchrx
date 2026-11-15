# TrialMatch Rx

Screens a patient against recruiting T2D/CKD trials with a live, auditable agent trace. Spec: [SPEC.md](SPEC.md).

Needs uv, Python 3.12, Node 22 and pnpm.

1. `make install` installs api (uv) and web (pnpm) dependencies.
2. `cp .env.example .env` and set `ANTHROPIC_API_KEY` (not needed for the M0 stubs).
3. `make dev` starts the api on :8045 and the web app on :3045; open http://localhost:3045/match.
4. `make check` runs ruff, mypy, pytest and the web typecheck + lint; `make types` regenerates `web/lib/api-types.ts`.
5. Offline demo: `make seed`, then `make record-demo` (needs `ANTHROPIC_API_KEY`) records the demo patient's match and closer runs into `data/fixtures/runs/`. Start with `DEMO_MODE=replay` in `.env` and `/api/match` and `/api/closer` replay them with their original timing (gaps capped at 0.2 s), no network or key needed. `GET /api/health` shows `demo_mode` and is `ok: false` in replay mode until both runs are recorded.

## Docker

Needs only Docker (no host Python or Node). `cp .env.example .env` and set `ANTHROPIC_API_KEY` first; the API reads `.env` at run time and neither image contains it.

1. `docker compose up --build` builds the API and web images and starts them, plus a local Caddy (`compose.override.yaml`) that routes `/api/*` to the API and everything else to Next, as prod does. Open http://localhost:8080/match. The API and web are also published on `127.0.0.1:8045` and `127.0.0.1:3045`.
2. The database lives on the `trialmatchrx_db` volume and starts empty. Seed it in the container with `docker compose run --rm api python -m scripts.seed_trials` (trials only; the cohort needs Synthea output on the host), or copy an existing `api/app.db` into it with the stack stopped:
   ```bash
   docker compose run --rm --no-deps -v "$PWD/api/app.db:/seed/app.db:ro" api python -c \
     "import sqlite3; sqlite3.connect('file:/seed/app.db?immutable=1', uri=True).backup(sqlite3.connect('/data/app.db'))"
   ```
3. `docker compose down` keeps the volume; `docker compose down -v` deletes it.

On ccl-vps only `compose.yaml` runs (`docker compose -f compose.yaml up -d`); the box's own Caddy does the routing.

**Where prod routing lives.** Not in this repo. The Caddy on ccl-vps is its own stack, whose source is in the KeyIDPro repo (`eodgooch/keyidpro`, `deploy/caddy/`). TrialMatch Rx is its block `deploy/caddy/sites/tmrx.crimsoncowlabs.com.caddy`: `https://tmrx.crimsoncowlabs.com`, `basic_auth` on every path, `/api/*` to `127.0.0.1:8045` and everything else to `127.0.0.1:3045`, so changing a port here means changing it there too. It goes out with that repo's `./scripts/deploy-caddy.sh`. The password's bcrypt line is only on the box, in `/app/caddy/secrets/tmrx.crimsoncowlabs.com.basicauth`; that repo's `deploy/caddy/sites/README.md` says how to make or change it.
