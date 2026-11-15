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

On ccl-vps only `compose.yaml` runs (`docker compose -f compose.yaml`, from `scripts/deploy.sh`); the box's own Caddy does the routing.

## Deploying to ccl-vps

From the Mac, on a commit with nothing uncommitted under `api/`, `web/`, `data/fixtures/`, `compose.yaml`. `scripts/deploy.sh` builds both images for linux/amd64, pushes them to the tailnet registry, and brings them up in `/app/trialmatchrx` (API on the box's `127.0.0.1:8045`, web on `127.0.0.1:3045`), rolling back if they don't come up healthy with `/api/health` `ok: true`. `scripts/load-data.sh` copies a seeded `api/app.db` into the stack's database volume. `--help` on either lists its settings.

First time:

1. Make the stack directory and its `.env` on the box. Only a person writes the secret; the deploy refuses without it and the model ids (use the ones in your local `.env`):
   ```bash
   ssh -t aaron@ccl-vps 'install -d -m 700 /app/trialmatchrx && umask 077 && nano /app/trialmatchrx/.env'
   ```
   ```
   ANTHROPIC_API_KEY=<your key>
   MODEL_COMPILE=<model id>
   MODEL_JUDGE=<model id>
   MODEL_PARSE=<model id>
   MODEL_CLOSER=<model id>
   DEMO_MODE=off
   ```
2. Deploy: `./scripts/deploy.sh --dry-run` (prints the tags, registry, host and stack dir), then `./scripts/deploy.sh`.
3. Load the data (needs a `make seed`ed `api/app.db`): `./scripts/load-data.sh --dry-run`, then `./scripts/load-data.sh`. It refuses a database on the box that already has rows; `--force` replaces it.
4. Check:
   ```bash
   ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml ps && curl -fsS 127.0.0.1:8045/api/health'
   ```

Later deploys are step 2 alone. Each successful one is a line in `/app/trialmatchrx/deploys.log`; the registry keeps the newest 3 tags. The registry is shared with KeyIDPro, so the delete + garbage-collect that prunes it runs under `flock -n /app/registry/.gc.lock`; a deploy that finds the lock held skips the prune and says so. KeyIDPro's deploy doesn't take that lock yet, so until it does, don't run the two deploys at the same time.
