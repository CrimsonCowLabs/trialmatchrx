
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
