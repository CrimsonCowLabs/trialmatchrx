// The first-time user guide (SPEC.md "First-time user guide"): the five steps and their copy,
// each step's links resolved from the pins `GET /api/guide` returns (with a "run it live"
// fallback when a pin is missing or its run is gone), and the panel's state in localStorage,
// with each change announced as a window event. Storage and event target are injectable, so
// all of it is tested in guide.test.ts; GuidePanel.tsx renders it.
import type { GuidePin } from "./api.ts";

export type GuideStepId = GuidePin["step"];

export interface GuideStep {
  id: GuideStepId;
  title: string;
  why: string;
  lookFor: string;
}

export const GUIDE_HEADER =
  "TrialMatch Rx checks a patient against recruiting clinical trials near Sacramento and shows its work: every verdict quotes the trial's rule and the patient's own words. Five short steps, about 4 minutes.";

export const GUIDE_FOOTER =
  "Home: demo patients · Match: paste your own note · Runs: every run, replayable · Trials: cached trials and their compiled rules · Eval: accuracy against expert labels.";

export const GUIDE_STEPS: readonly GuideStep[] = [
  {
    id: "als",
    title: "Watch it work (ALS)",
    why: "Checking one patient against one trial takes a coordinator about an hour.",
    lookFor:
      "The trace panel: every step is visible, numeric rules are checked by code, and AI only judges what's actually ambiguous. Click Find trials for Daniel Moreno (ALS). A run takes about 90 seconds, so you can go on and come back; it's saved under Runs.",
  },
  {
    id: "ipf",
    title: "The catch (IPF)",
    why: "Exclusions buried deep in a protocol are easy to miss.",
    lookFor:
      "The red ✕ on ifetroban. Richard's FEV1/FVC is 0.66, and the trial excludes anything below 0.7. The trial's rule and Richard's own words are quoted right on the row. Click Why? to jump to the trace step that decided it.",
  },
  {
    id: "ipf_flip",
    title: "Is it really reading the data? (IPF)",
    why: "Changing one number should change only what it justifies.",
    lookFor:
      "FEV1/FVC 0.66 → 0.75. Ifetroban opens up, along with other trials excluded for the same reason.",
  },
  {
    id: "pah",
    title: "Next steps (PAH, in Spanish)",
    why: '"Unknown" should become a to-do list, not a dead end.',
    lookFor:
      "The follow-up tests to order, a draft email to the study's coordinator, and Lucía's summary in Spanish.",
  },
  {
    id: "feasibility",
    title: "For trial designers (optional)",
    why: "The same engine, run in reverse.",
    lookFor:
      "How many of 1,000 synthetic patients qualify, which rule shrinks the pool most, and the slider changing the count instantly. Then Eval for the TREC benchmark.",
  },
];

export interface GuideLink {
  label: string;
  href: string;
}

/** One step's buttons, and the line that replaces them when its pin is missing or gone. */
export interface StepLinks {
  links: GuideLink[];
  fallback: string | null;
}

const HOME: GuideLink = { label: "Go to Home", href: "/" };

/** A pin whose run still exists. */
type LivePin = GuidePin & { run_id: string };

/** `/match/{run}`, deep-linked to the trial when the pin names one. */
function matchHref(pin: LivePin): string {
  const run = `/match/${encodeURIComponent(pin.run_id)}`;
  return pin.nct_id ? `${run}?${new URLSearchParams({ trial: pin.nct_id })}` : run;
}

/** The pin for `step` when its run still exists. */
function livePin(
  pins: readonly GuidePin[],
  step: GuideStepId,
): LivePin | null {
  const pin = pins.find((p) => p.step === step);
  return pin && pin.run_id !== null && pin.run_exists ? { ...pin, run_id: pin.run_id } : null;
}

/** Every step's links, from the pinned runs (`GET /api/guide`); pass [] when that call failed. */
export function guideLinks(pins: readonly GuidePin[]): Record<GuideStepId, StepLinks> {
  const als = livePin(pins, "als");
  const ipf = livePin(pins, "ipf");
  const flip = livePin(pins, "ipf_flip");
  const pah = livePin(pins, "pah");
  const feasibilityNct = pins.find((p) => p.step === "feasibility")?.nct_id ?? null;
  return {
    // Home already selects Daniel Moreno (the first demo patient); it reads no URL param.
    als: {
      links: als ? [HOME, { label: "See a finished run", href: matchHref(als) }] : [HOME],
      fallback: null,
    },
    ipf: ipf
      ? { links: [{ label: "Open", href: matchHref(ipf) }], fallback: null }
      : {
          links: [HOME],
          fallback: "Find trials for Richard Hale (IPF) on Home, then open ifetroban.",
        },
    // The note can only be edited on Match (Home shows it read-only), so the fallback goes there.
    ipf_flip:
      ipf && flip
        ? {
            links: [
              { label: "Before", href: matchHref(ipf) },
              { label: "After", href: matchHref(flip) },
            ],
            fallback: null,
          }
        : {
            links: [{ label: "Go to Match", href: "/match" }],
            fallback:
              "On Match, pick Richard Hale (IPF) and click Find trials, then change FEV1/FVC 0.66 to 0.75 in the note and run it again.",
          },
    pah: pah
      ? {
          links: [{ label: "Open", href: `/closer/${encodeURIComponent(pah.run_id)}` }],
          fallback: null,
        }
      : {
          links: [HOME],
          fallback:
            "Find trials for Lucía Ramírez (PAH) on Home, open the top trial and click Next steps.",
        },
    feasibility: {
      links: [
        // Unpinned, the button names where it goes: pick a compiled trial on Trials.
        feasibilityNct
          ? { label: "Feasibility", href: `/feasibility/${encodeURIComponent(feasibilityNct)}` }
          : { label: "Trials", href: "/trials" },
        { label: "Eval", href: "/eval" },
      ],
      fallback: null,
    },
  };
}

// --- Stored state ---

/** The bit of `Storage` the guide uses; injected so tests can pass fakes. */
export type GuideStorage = Pick<Storage, "getItem" | "setItem">;

export interface GuideState {
  /** The reader's last expand / collapse; null until they choose, so the layout decides. */
  open: boolean | null;
  /** Visited steps, in the order first visited. */
  visited: GuideStepId[];
}

/** A change to the guide, announced on `window` as a `GUIDE_EVENT` CustomEvent. */
export type GuideAction =
  | { type: "mark"; step: GuideStepId }
  | { type: "open"; open: boolean }
  | { type: "reset" };

export const GUIDE_STORAGE_KEY = "tmrx.guide";
export const GUIDE_EVENT = "tmrx:guide";
const VERSION = 1;

const STEP_IDS: ReadonlySet<string> = new Set(GUIDE_STEPS.map((s) => s.id));

const FIRST_VISIT: Readonly<GuideState> = Object.freeze({ open: null, visited: [] });

/** Whether the panel shows expanded: the reader's choice, else open on a wide screen (it opens
 *  by itself on the first visit) and collapsed on a narrow one (a bottom sheet). */
export function isGuideOpen(state: GuideState, { narrow }: { narrow: boolean }): boolean {
  return state.open ?? !narrow;
}

export function applyGuideAction(state: GuideState, action: GuideAction): GuideState {
  switch (action.type) {
    case "mark":
      return state.visited.includes(action.step)
        ? state
        : { ...state, visited: [...state.visited, action.step] };
    case "open":
      return { ...state, open: action.open };
    case "reset":
      return { ...state, visited: [] };
  }
}

/** The stored state; the first-visit state when storage is missing, throws, or holds anything
 *  but a valid current-version record. */
export function readGuideState(storage: GuideStorage | null): GuideState {
  const firstVisit = (): GuideState => ({ ...FIRST_VISIT, visited: [] });
  let parsed: unknown;
  try {
    const raw = storage?.getItem(GUIDE_STORAGE_KEY) ?? null;
    if (raw === null) return firstVisit();
    parsed = JSON.parse(raw);
  } catch {
    return firstVisit();
  }
  if (typeof parsed !== "object" || parsed === null) return firstVisit();
  const { v, open, visited } = parsed as Record<string, unknown>;
  if (v !== VERSION || !(open === null || typeof open === "boolean") || !Array.isArray(visited)) {
    return firstVisit();
  }
  const known = visited.filter(
    (s): s is GuideStepId => typeof s === "string" && STEP_IDS.has(s),
  );
  return { open, visited: [...new Set(known)] };
}

function writeGuideState(storage: GuideStorage | null, state: GuideState): void {
  try {
    storage?.setItem(GUIDE_STORAGE_KEY, JSON.stringify({ v: VERSION, ...state }));
  } catch {
    // Storage full or blocked: the panel still updates from the event, it just won't persist.
  }
}

/** Where state is stored and changes announced; defaults to `localStorage` and `window`. */
export interface GuideDeps {
  storage?: GuideStorage | null;
  target?: EventTarget | null;
}

/** `window.localStorage`, or null when there is no window or touching it throws (blocked). */
function browserStorage(): GuideStorage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** `window`, or null on the server. */
function browserTarget(): EventTarget | null {
  return typeof window === "undefined" ? null : window;
}

function update(action: GuideAction, deps: GuideDeps): void {
  const storage = deps.storage === undefined ? browserStorage() : deps.storage;
  const target = deps.target === undefined ? browserTarget() : deps.target;
  writeGuideState(storage, applyGuideAction(readGuideState(storage), action));
  target?.dispatchEvent(new CustomEvent<GuideAction>(GUIDE_EVENT, { detail: action }));
}

/** Check a step (its link was clicked, or the ALS run started); a mounted panel updates. */
export function markGuideStep(step: GuideStepId, deps: GuideDeps = {}): void {
  update({ type: "mark", step }, deps);
}

/** Remember the panel expanded or collapsed. */
export function setGuideOpen(open: boolean, deps: GuideDeps = {}): void {
  update({ type: "open", open }, deps);
}

/** Clear every check, for the next reader; the panel stays as it is. */
export function resetGuide(deps: GuideDeps = {}): void {
  update({ type: "reset" }, deps);
}

/** The state stored in this browser (the first-visit state on the server). */
export function loadGuideState(): GuideState {
  return readGuideState(browserStorage());
}
