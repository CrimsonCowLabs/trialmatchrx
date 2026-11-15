// The demo match request the home page's "Find trials" starts.
import type { MatchRequest } from "./api";

// HACK(demo): the synthetic demo patient from SPEC.md's demo script, with the demo condition and
// radius. A copy of the match form's prefill (web/app/match/page.tsx), which is left untouched
// while its redesign (#33) is in flight; the form should import this once that lands.
export const DEMO_MATCH: MatchRequest = {
  note: "61-year-old man with type 2 diabetes, HbA1c 8.4%, eGFR 48, on metformin. Lives in Sacramento.",
  condition: "type 2 diabetes",
  radius_mi: 50,
};
