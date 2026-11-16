# TrialMatch Rx

Screens a patient against recruiting T2D/CKD trials with a live, auditable agent trace. Spec: [SPEC.md](SPEC.md).

Needs uv, Python 3.12, Node 22 and pnpm.

1. `make install` installs api (uv) and web (pnpm) dependencies.
2. `cp .env.example .env` and set `ANTHROPIC_API_KEY` (not needed for the M0 stubs).
3. `make dev-user` creates the local account and prints its email and password; `make dev` starts the api on :8045 and the web app on :3045. Open http://localhost:3045/match (use `localhost`, not `127.0.0.1`: the session cookie is set for the API's host) and sign in. Every page but `/`, `/login` and the invite and reset links needs a session, and so does every `/api` route but `GET /api/health`, `/api/auth/*` and `POST /api/access-requests`.
4. `make check` runs ruff, mypy, pytest and the web typecheck + lint; `make types` regenerates `web/lib/api-types.ts`.
5. Offline demo: `make seed`, then `make record-demo` (needs `ANTHROPIC_API_KEY`) records a match run and a closer run for each demo patient (`als`, `ipf`, `pah`, `t2d`) into `data/fixtures/runs/` (`match-<id>.json`, `closer-<id>.json`) and prints each run's LLM cost. Record or re-record one patient at a time with `make record-demo ARGS="--patient als"` (repeatable). Start with `DEMO_MODE=replay` in `.env` and `/api/match` and `/api/closer` replay them with their original timing (gaps capped at 0.2 s), no network or key needed. Replay picks the patient from the note it is sent (whitespace and case are ignored); a note with no recording gets a 503 that says so. `GET /api/health` shows `demo_mode`, lists the recorded `demo_patients`, and is `ok: false` in replay mode until at least one patient is recorded and every recorded match has its closer run.

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

**Where prod routing lives.** Not in this repo. The Caddy on ccl-vps is its own stack, whose source is in the KeyIDPro repo (`eodgooch/keyidpro`, `deploy/caddy/`). TrialMatch Rx is its block `deploy/caddy/sites/tmrx.crimsoncowlabs.com.caddy`: `https://tmrx.crimsoncowlabs.com`, `basic_auth` on every path, `/api/*` to `127.0.0.1:8045` and everything else to `127.0.0.1:3045`, so changing a port here means changing it there too. It goes out with that repo's `./scripts/deploy-caddy.sh`. The password's bcrypt line is only on the box, in `/app/caddy/secrets/tmrx.crimsoncowlabs.com.basicauth`; that repo's `deploy/caddy/sites/README.md` says how to make or change it.

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

### Pinning the first-time guide's runs

The guide's links come from the `guide_pins` table in the prod database (SPEC.md, "First-time user guide", Pins). Record the runs live in the prod UI, take each run id from the Runs page, then pin them in the running API container (it has no `make`; `python -m scripts.guide_pin` from its workdir `/app/api` is what `make guide-pin` runs):

```bash
ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api python -m scripts.guide_pin als RUN_ID'
```

The arguments are `make guide-pin`'s `ARGS`: `als|ipf|ipf_flip RUN_ID [--trial NCT]` (a done match run; `--trial` must be one of its matches), `pah RUN_ID` (a done closer run; the trial is the one it ran on), `feasibility --trial NCT` (a cached trial, no run), `--remove STEP`. With no arguments it lists every step as `pinned` / `MISSING` / `RUN GONE` and exits 1 unless all five are pinned to runs that still exist, so run it bare as the last check before judging.

### Managing accounts

Accounts live in the `users` table of the prod database (SPEC.md, "Marketing and accounts", Admin CLI). Run the commands in the API container the same way as `guide_pin` (`python -m scripts.users` is what `make users` runs, `python -m scripts.disable_user EMAIL` is `make disable-user EMAIL=...`):

```bash
ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api python -m scripts.users'
ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api python -m scripts.disable_user ana@example.com'
```

`users` lists every account, oldest first, with its created date, last sign-in, number of passkeys, whether a password is set, and its disabled date (times in UTC). `disable_user` ends all of that account's sessions and blocks sign-in; the row stays, so a run's `created_by` still resolves. An unknown email exits 2 and changes nothing; an already-disabled account says so and keeps its first disabled date.

Request-access submissions from the form on `/` live in the `access_requests` table. `make access-requests` (`python -m scripts.access_requests`) lists them newest first: when each was received (UTC), name, work email, organization and role, with the message, if any, on the line below. Nothing is emailed; reply yourself and send an invite.

```bash
ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api python -m scripts.access_requests'
```

The form drops a submission with its hidden honeypot field filled (it still says thanks) and takes at most 3 per hour from one IP; the 4th reads "You've already sent a few requests. Try again in an hour."

### Updating the marketing page

The public page at `/` (SPEC.md, "Marketing and accounts") takes its copy and three config values from `web/lib/marketing.ts`; a change is an edit plus a deploy.

- `DEMO_VIDEO_ID`: the YouTube video's 11-character ID. While it's `null` the poster reads "Demo video coming soon"; once set, `youtube-nocookie.com` loads only when someone clicks play.
- `AWARD_RESULTS_URL` and `AWARD_PHOTOS`: the award section stays hidden until both are set. Photos are static files in `web/public/award/` (`{ src: "/award/stage.jpg", alt, width, height }`).

The moment screenshots in `web/public/moments/` are real captures of the app with `DEMO_MODE=replay` (synthetic patients), at 1600px and 390px wide: Match is the IPF demo run with the first Needs info trial open, Feasibility is NCT07664553, and Proof is "Why?" on ifetroban's (NCT05571059) FEV1/FVC exclusion. `web/public/og.png` (1200x630) is the page's own hero. Recapture them after a visible UI change.

### Inviting someone

Accounts are invite-only and nothing sends email (SPEC.md, "Marketing and accounts"). Locally, `make invite EMAIL=someone@example.com` prints the link. In prod, run what it runs inside the API container:

```bash
ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api python -m scripts.invite someone@example.com'
```

It prints a `https://tmrx.crimsoncowlabs.com/invite/<token>` link (the origin is `APP_URL`, set in `compose.yaml`; `--base-url URL` overrides it). Send it yourself. The link works once and expires after 7 days; on it the person sets a password and is signed in. An email that already has an account is refused and nothing is created. Inviting the same email again prints a new link and cancels the older unused ones, which then read as expired.
