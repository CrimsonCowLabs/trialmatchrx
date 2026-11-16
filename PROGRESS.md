
## 2026-11-15 17:14 first-time-guide/ipf-card-note
- Reverted the IPF demo card's note (web/lib/demo.ts) from FEV1/FVC 0.75 back to 0.66; 5d569fb had changed it to make the flip run. The card has to stay 0.66: it is the exclusion the pitch and guide step 2 show, replay matches the recorded 0.66 note, and the flip is a one-off edit in the Match page's note box. Kept 5d569fb's .gitignore change (demo.txt).
- Tests: `make check` green.
- Decisions:
  - User decision: committed straight to main, no PR.
