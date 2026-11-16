"use client";

// The first-time user guide (SPEC.md "First-time user guide"), mounted once in the app shell.
// Its shape depends on the screen width:
// - from 2xl (96rem), a column docked on the right of the shell that collapses to a slim handle;
// - md to 2xl, a modal drawer over the page from the right, closed by its X, Escape or the
//   backdrop (a docked column there would crush the match page's results beside its trace);
// - below md, a bottom sheet above the tab bar whose collapsed form is a one-line handle.
// The sidebar's GuideButton opens and closes it on desktop. Copy, links and state live in
// lib/guide.ts; pins come from GET /api/guide once on mount (a failed call reads as no pins).
import { Check, ChevronDown, ChevronUp, ListChecks, PanelRightClose, X } from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { buttonVariants } from "@/components/ui/button";
import { api, type GuidePin } from "@/lib/api";
import {
  GUIDE_EVENT,
  GUIDE_FOOTER,
  GUIDE_HEADER,
  GUIDE_STEPS,
  applyGuideAction,
  guideLinks,
  isGuideOpen,
  linkMarksStep,
  loadGuideState,
  markGuideStep,
  resetGuide,
  setGuideOpen,
  type GuideAction,
  type GuideLink,
  type GuideState,
  type GuideStep,
  type StepLinks,
} from "@/lib/guide";
import { cn } from "@/lib/utils";

const PANEL_ID = "guide-panel";
const TITLE_ID = "guide-panel-title";
/** Marks the controls that reopen the guide, so focus can return to whichever is showing. */
const REOPEN_ATTR = "data-guide-reopen";

const FOCUS_RING = "outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// --- The guide state, shared by the panel and the sidebar button ---

let cachedState: GuideState | null = null;
const listeners = new Set<() => void>();

function onGuideEvent(e: Event) {
  cachedState = applyGuideAction(guideSnapshot(), (e as CustomEvent<GuideAction>).detail);
  listeners.forEach((l) => l());
}

function subscribeGuide(listener: () => void) {
  if (listeners.size === 0) {
    cachedState = null; // Re-read storage: a change made while nothing listened was only stored.
    window.addEventListener(GUIDE_EVENT, onGuideEvent);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener(GUIDE_EVENT, onGuideEvent);
  };
}

function guideSnapshot(): GuideState {
  return (cachedState ??= loadGuideState());
}

/** The guide state, or null while server-rendering and hydrating (storage is browser-only). */
function useGuideState(): GuideState | null {
  return useSyncExternalStore(subscribeGuide, guideSnapshot, () => null);
}

type Layout = "sheet" | "drawer" | "docked";

const DOCKED = "(width >= 96rem)";
const DRAWER = "(width >= 48rem)";

function subscribeLayout(listener: () => void) {
  const queries = [DOCKED, DRAWER].map((q) => window.matchMedia(q));
  queries.forEach((q) => q.addEventListener("change", listener));
  return () => queries.forEach((q) => q.removeEventListener("change", listener));
}

function layoutSnapshot(): Layout {
  if (window.matchMedia(DOCKED).matches) return "docked";
  return window.matchMedia(DRAWER).matches ? "drawer" : "sheet";
}

function useLayout(): Layout | null {
  return useSyncExternalStore(subscribeLayout, layoutSnapshot, () => null);
}

/** Set by a reader's own open / collapse, so the panel moves focus once it re-renders (a link
 *  that collapses the sheet doesn't: focus belongs to the page it opens). */
let moveFocus = false;

function toggleGuide(open: boolean) {
  moveFocus = true;
  setGuideOpen(open);
}

function progress(state: GuideState): string {
  return `${state.visited.length} of ${GUIDE_STEPS.length}`;
}

// --- The sidebar button ---

/** "Guide" below the sidebar nav (md and up): opens the panel, or closes it when open. */
export function GuideButton() {
  const state = useGuideState();
  const layout = useLayout();
  if (!state || !layout || layout === "sheet") return null;
  const open = isGuideOpen(state, { narrow: false });
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={PANEL_ID}
      {...{ [REOPEN_ATTR]: "" }}
      onClick={() => toggleGuide(!open)}
      className={`mt-3 flex h-11 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-ink-2 hover:bg-surface-sunken ${FOCUS_RING}`}
    >
      <ListChecks aria-hidden className="size-4 shrink-0" />
      <span className="flex-1 text-left">Guide</span>
      <span className="font-mono text-xs text-ink-4 tabular-nums">{progress(state)}</span>
    </button>
  );
}

// --- The panel ---

function StepItem({
  number,
  step,
  links,
  visited,
  onFollow,
}: {
  number: number;
  step: GuideStep;
  links: StepLinks | null;
  visited: boolean;
  onFollow: (step: GuideStep, link: GuideLink) => void;
}) {
  return (
    <li
      className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3"
      data-testid={`guide-step-${step.id}`}
    >
      <span
        className={cn(
          "flex size-7 items-center justify-center rounded-full font-mono text-xs font-medium tabular-nums",
          visited ? "bg-teal-tint text-teal-strong" : "border border-line-strong text-ink-3",
        )}
        aria-hidden
      >
        {visited ? <Check className="size-3.5" strokeWidth={3} /> : number}
      </span>
      <div className="flex min-w-0 flex-col gap-1.5">
        <h3 className="pt-0.5 text-sm leading-snug font-semibold text-ink">
          {step.title}
          {visited && <span className="sr-only"> (visited)</span>}
        </h3>
        <p className="text-[0.8125rem] text-ink-3 italic">{step.why}</p>
        <p className="text-[0.8125rem] text-ink-2">{step.lookFor}</p>
        {links?.fallback && (
          <p className="rounded-md bg-surface-sunken px-2.5 py-1.5 text-[0.8125rem] text-ink-2">
            {links.fallback}
          </p>
        )}
        {links ? (
          <div className="flex flex-wrap gap-2 pt-0.5">
            {links.links.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                onClick={() => onFollow(step, link)}
                className={buttonVariants({ variant: "outline", size: "sm" })}
              >
                {link.label}
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-xs text-ink-4">Loading links…</p>
        )}
      </div>
    </li>
  );
}

function GuideBody({
  state,
  pins,
  onFollow,
}: {
  state: GuideState;
  pins: GuidePin[] | null;
  onFollow: (step: GuideStep, link: GuideLink) => void;
}) {
  const links = pins ? guideLinks(pins) : null;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto overscroll-contain px-4 py-4">
      <p className="text-sm text-ink-2">{GUIDE_HEADER}</p>
      <ol className="flex flex-col gap-5">
        {GUIDE_STEPS.map((step, i) => (
          <StepItem
            key={step.id}
            number={i + 1}
            step={step}
            links={links?.[step.id] ?? null}
            visited={state.visited.includes(step.id)}
            onFollow={onFollow}
          />
        ))}
      </ol>
      <p className="border-t border-line-soft pt-4 text-xs text-ink-4">{GUIDE_FOOTER}</p>
      <button
        type="button"
        onClick={() => resetGuide()}
        className="self-start text-xs font-medium link hover:underline"
      >
        Reset
      </button>
    </div>
  );
}

/** Per layout: how the open panel sits, and its collapse button. */
const LAYOUT: Record<Layout, { panel: string; closeIcon: typeof X; closeLabel: string }> = {
  // The bottom offset is the tab bar's h-16 plus the safe-area inset (AppShell).
  sheet: {
    panel:
      "fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-30 max-h-[70dvh] rounded-t-2xl border-t shadow-[0_-8px_24px_color-mix(in_srgb,var(--ink)_8%,transparent)]",
    closeIcon: ChevronDown,
    closeLabel: "Collapse the guide",
  },
  // Above the backdrop (z-50) and the trace's mobile detail sheet (z-50, below lg).
  drawer: {
    panel:
      "fixed inset-y-0 right-0 z-[60] w-96 max-w-full border-l shadow-[-8px_0_24px_color-mix(in_srgb,var(--ink)_10%,transparent)]",
    closeIcon: X,
    closeLabel: "Close the guide",
  },
  docked: {
    panel: "sticky top-0 h-dvh w-80 shrink-0 border-l",
    closeIcon: PanelRightClose,
    closeLabel: "Collapse the guide",
  },
};

/** The collapsed guide: the one-line handle above the tab bar, or the docked column's slim
 *  handle. In the drawer layout it is just closed (the sidebar button reopens it). */
function CollapsedHandle({ state, layout }: { state: GuideState; layout: Layout }) {
  if (layout === "drawer") return null;
  const toggleProps = {
    type: "button" as const,
    "aria-expanded": false,
    "aria-controls": PANEL_ID,
    [REOPEN_ATTR]: "",
    "data-testid": "guide-handle",
    onClick: () => toggleGuide(true),
  };
  if (layout === "sheet") {
    return (
      // h-11: AppShell's mobile bottom padding leaves room for it above the tab bar.
      <button
        {...toggleProps}
        className={`fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-30 flex h-11 items-center gap-2 border-t border-line bg-surface px-4 text-sm font-medium text-ink-2 focus-visible:ring-inset ${FOCUS_RING}`}
      >
        <ListChecks aria-hidden className="size-4 shrink-0 text-teal-strong" />
        <span className="flex-1 text-left">Guide · {progress(state)}</span>
        <ChevronUp aria-hidden className="size-4 text-ink-4" />
      </button>
    );
  }
  return (
    <button
      {...toggleProps}
      aria-label={`Open the guide, ${progress(state)} visited`}
      className={`sticky top-0 flex h-dvh w-10 shrink-0 flex-col items-center gap-2 border-l bg-surface pt-5 text-ink-3 hover:bg-surface-sunken focus-visible:ring-inset ${FOCUS_RING}`}
    >
      <ListChecks aria-hidden className="size-4" />
      <span className="font-mono text-xs tabular-nums [writing-mode:vertical-rl]">
        Guide · {progress(state)}
      </span>
    </button>
  );
}

const FOCUSABLE = "a[href], button:not([disabled])";

/** Keeps Tab inside the modal drawer. */
function trapTab(e: ReactKeyboardEvent<HTMLElement>) {
  if (e.key !== "Tab") return;
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE));
  const first = items[0];
  const last = items.at(-1);
  if (!first || !last) return;
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

export function GuidePanel() {
  const state = useGuideState();
  const layout = useLayout();
  const [pins, setPins] = useState<GuidePin[] | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    api.listGuidePins().then(
      (p) => !cancelled && setPins(p),
      // No pins: every step falls back to running its card live; the guide still works.
      () => !cancelled && setPins([]),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const open = state && layout ? isGuideOpen(state, { narrow: layout === "sheet" }) : false;
  const drawerOpen = open && layout === "drawer";

  // After the reader's own open / collapse: focus the collapse button, or the visible control
  // that reopens the guide.
  useEffect(() => {
    if (!moveFocus) return;
    moveFocus = false;
    if (open) {
      closeRef.current?.focus();
      return;
    }
    const reopen = Array.from(document.querySelectorAll<HTMLElement>(`[${REOPEN_ATTR}]`)).find(
      (el) => el.getClientRects().length > 0,
    );
    reopen?.focus();
  }, [open, layout]);

  // The drawer is modal: Escape closes it from anywhere. The sheet and the docked column
  // listen only while focus is inside them (onKeyDown below).
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && toggleGuide(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  if (!state || !layout) return null;
  const config = LAYOUT[layout];
  const CloseIcon = config.closeIcon;

  function follow(step: GuideStep, link: GuideLink) {
    if (linkMarksStep(step.id, link)) markGuideStep(step.id);
    // A sheet or drawer covers the page the link opens; the docked column stays.
    if (layout !== "docked") setGuideOpen(false);
  }

  return (
    <>
      {!open && <CollapsedHandle state={state} layout={layout} />}
      {drawerOpen && (
        <div
          aria-hidden
          onClick={() => toggleGuide(false)}
          className="fixed inset-0 z-50 bg-ink/20"
        />
      )}
      {/* Always in the DOM (hidden when collapsed) so every toggle's aria-controls resolves. */}
      <section
        id={PANEL_ID}
        hidden={!open}
        aria-labelledby={TITLE_ID}
        role={drawerOpen ? "dialog" : undefined}
        aria-modal={drawerOpen || undefined}
        data-testid={open ? "guide-panel" : undefined}
        onKeyDown={(e) => {
          if (drawerOpen) trapTab(e);
          else if (e.key === "Escape") toggleGuide(false);
        }}
        className={cn("flex flex-col bg-surface", config.panel, !open && "hidden")}
      >
        <div className="flex shrink-0 items-center gap-3 border-b border-line-soft px-4 py-3">
          <h2 id={TITLE_ID} className="flex-1 text-base font-semibold">
            Guide{" "}
            <span className="ml-1 font-mono text-xs font-medium text-ink-4 tabular-nums">
              {progress(state)}
            </span>
          </h2>
          <button
            ref={closeRef}
            type="button"
            aria-expanded
            aria-controls={PANEL_ID}
            aria-label={config.closeLabel}
            onClick={() => toggleGuide(false)}
            className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
          >
            <CloseIcon aria-hidden />
          </button>
        </div>
        <GuideBody state={state} pins={pins} onFollow={follow} />
      </section>
    </>
  );
}
