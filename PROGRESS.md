
## 2026-11-15 17:14 first-time-guide/ipf-card-note
- Reverted the IPF demo card's note (web/lib/demo.ts) from FEV1/FVC 0.75 back to 0.66; 5d569fb had changed it to make the flip run. The card has to stay 0.66: it is the exclusion the pitch and guide step 2 show, replay matches the recorded 0.66 note, and the flip is a one-off edit in the Match page's note box. Kept 5d569fb's .gitignore change (demo.txt).
- Tests: `make check` green.
- Decisions:
  - User decision: committed straight to main, no PR.

## 2026-11-16 10:50 marketing-and-accounts/spec
- SPEC.md: authentication is no longer out of scope. A new "Marketing and accounts" section covers:
  - a public marketing page at `/`, with the HackRx 2026 award badge, a click-to-load YouTube demo, and request access;
  - invite-only accounts with passkey and email/password login, built in FastAPI;
  - cookie sessions, an admin CLI, and the cutover from Caddy basic_auth.
- Tests: none (spec only). `make check` green.
- Decisions:
  - User decision: invite-only accounts replace basic_auth; every signed-in user sees all runs; new runs record `created_by`.
  - User decision: the marketing page is at `/` on the same app and domain; only Home moves, to `/app`; the other app paths stay.
  - User decision: auth is self-built in FastAPI (`py_webauthn`, `argon2-cffi`), with users, sessions, invites and access requests in SQLite; no hosted provider.
  - User decision: no email sending for now; invite and reset links come from a CLI.
  - User decision: the passkey domain is `tmrx.crimsoncowlabs.com`; a later domain move means re-registering passkeys.
  - User decision: the award badge is text in the app's styles, linking to sachacks.io; the results link and photos come later; no accuracy numbers until a scored TREC run exists.
  - User decision: the design is built in code and reviewed from screenshots, not mocked first.
  - User decision: the web side uses `@simplewebauthn/browser` for passkey encoding, because the browser's WebAuthn JSON helpers aren't available everywhere yet. Third new dependency, after `py_webauthn` and `argon2-cffi`.
  - User decision: the video ID, results link and photo list are constants in `web/lib/marketing.ts`, and the photos go in `web/public/award/`. Changing them means an edit plus a deploy.
  - User decision: the footer reads "© 2026 Crimson Cow Labs · Synthetic data only".

## 2026-11-16 11:06 marketing-and-accounts/home-to-app
- Home moved from `/` to `/app` (#12). The web app is split into two Next.js route groups under web/app:
  - `(shell)`: its layout wraps pages in AppShell (sidebar, tab bar, guide panel). Holds `app/` (the old Home, unchanged) and Match, Runs, Trials, Eval, Feasibility and Closer. Route groups add no URL segment, so `/match/<id>`, `/closer/<id>` etc. keep their paths.
  - `(bare)`: a plain layout with no sidebar, tab bar or guide panel. Holds only the `/` placeholder for now; `/login`, `/invite/[token]` and `/reset/[token]` go here later.
  - The root layout keeps only `<html>`, `<body>`, fonts and metadata.
- `/` is a placeholder in the bare layout: the product name, one line and an "Open the app" link to `/app`. It is tagged `HACK(demo):`; the marketing page ticket replaces it.
- Links moved to `/app`, all through one `HOME_HREF` constant in lib/nav.ts: the nav's Home item, the guide's "Go to Home" (lib/guide.ts), the sidebar logo (AppShell), the "Home" breadcrumb on Match, Runs, Trials and Eval, and the placeholder's link.
- Code review (standards + spec, against origin/main): added the `HACK(demo):` tag to the placeholder, replaced the eight `"/app"` literals with `HOME_HREF`, rewrapped two long comments, and dropped the brand icon from the placeholder so it stays minimal. No spec gaps found.
- GuidePanel's "does following this link check the step" rule compared hrefs to a literal `"/"`. It moved to lib/guide.ts as `linkMarksStep`, which compares to the Home link's own href, and now has a test.
- Tests: nav.test.ts covers `/app` and `/app/` highlighting Home, `/` and `/apps` highlighting nothing; guide.test.ts covers the Go to Home links at `/app` and `linkMarksStep`. `make check` green (ruff, mypy, 498 pytest, typecheck, lint, 174 web tests, script tests).
- Visual check: ran `make dev API_PORT=8145 WEB_PORT=3145` and took headless Chromium screenshots of `/` and `/app` at 1440px and 390px. `/` shows no sidebar, tab bar or guide; `/app` shows the shell with Home highlighted. The data cards on `/app` read "Failed to fetch" there because the API's CORS list only allows :3045; this is unrelated to the change.
- Decisions:
  - Route groups are named `(shell)` and `(bare)`, after the two layouts, rather than after login state; auth gating is a separate concern.
  - `/` highlights no nav item: it's outside the shell, so no nav renders there anyway.
  - Any path under `/app` highlights Home, so a later `/app/account` will too unless the accounts ticket changes the SECTION map in lib/nav.ts.
  - The placeholder's line is "Match patients to recruiting clinical trials, and see why." (adapted from Home's title) and its button reads "Open the app".
  - The guide's fallback copy still says "on Home"; Home is still the page's name, only its URL changed.
  - compose.yaml's web healthcheck still fetches `/`, which still returns 200 (the placeholder, and later the public marketing page).
