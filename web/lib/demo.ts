// The demo match request: the home page's "Find trials" starts it and the match form prefills it.
import type { MatchRequest } from "./api";

// HACK(demo): the synthetic demo patient from SPEC.md's demo script, with the demo condition and
// radius.
export const DEMO_MATCH = {
  note: "61-year-old man with type 2 diabetes, HbA1c 8.4%, eGFR 48, on metformin. Lives in Sacramento.",
  condition: "type 2 diabetes",
  radius_mi: 50,
} satisfies MatchRequest;
