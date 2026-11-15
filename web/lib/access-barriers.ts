// Access barriers (issue #53): criteria that shut people out for reasons other than health,
// flagged by the API's rule-based classifier. Only a type import from ./api.ts and the pure
// ./format.ts, so node:test can load this file directly.
import type { Schemas } from "./api.ts";
import { countNoun } from "./format.ts";

export type AccessBarrier = NonNullable<Schemas["Criterion"]["access_barrier"]>;

const TAGS: Record<AccessBarrier, { label: string; who: string }> = {
  language: { label: "Language", who: "don't read or speak English" },
  visit_burden: { label: "Visit burden", who: "can't make frequent visits or overnight stays" },
  technology: { label: "Technology", who: "lack a smartphone, internet or a computer" },
  support: { label: "Support", who: "have no caregiver, study partner or transportation" },
};

/** The tag on a flagged criterion row, and its hover text. */
export function barrierTag(barrier: AccessBarrier): { label: string; title: string } {
  const { label, who } = TAGS[barrier];
  return { label, title: `Access barrier: shuts out people who ${who}` };
}

/** How many of a trial's criteria (or verdicts) carry an access barrier flag. */
export function barrierCount(items: { access_barrier?: AccessBarrier | null }[]): number {
  return items.filter((i) => i.access_barrier).length;
}

/** "2 access barriers" for a trial; null when it has none (nothing is shown). */
export function barrierCountLabel(n: number): string | null {
  return n > 0 ? countNoun(n, "access barrier", "access barriers") : null;
}
