// The global app shell: a sidebar at md and up, a bottom tab bar below md (never both), the
// first-time user guide (GuidePanel: docked right, a drawer, or a bottom sheet), and the
// page frame every route renders in. The frame owns the 16px mobile gutters and padding; a page
// picks its width with <Page width=...>. The route-aware nav suspends under cacheComponents on
// dynamic routes, so each nav has a static fallback (same items, nothing highlighted).
import Image from "next/image";
import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { GuidePanel } from "./GuidePanel";
import { SidebarNav, SidebarNavFallback, TabBarNav, TabBarNavFallback } from "./ShellNav";

/** The brand icon (public/brand, see its README): two rings = patient + trial, the lens = the
 *  match. Decorative; the wordmark beside it names the link. */
function BrandMark() {
  return <Image src="/brand/icon.svg" alt="" width={26} height={26} className="shrink-0" />;
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-6 border-r bg-surface p-4 md:flex">
        <Link href="/" className="flex items-center gap-2.5 px-1 font-semibold tracking-tight">
          <BrandMark />
          TrialMatch Rx
        </Link>
        <Suspense fallback={<SidebarNavFallback />}>
          <SidebarNav />
        </Suspense>
        <p className="text-xs text-ink-4">Synthetic data only</p>
      </aside>
      {/* Bottom padding below md clears the fixed tab bar (h-16 plus the safe-area inset) and
          the collapsed guide handle above it (h-11). */}
      <main className="flex min-w-0 flex-1 flex-col px-4 pt-6 pb-[calc(8.25rem+env(safe-area-inset-bottom))] sm:px-8 sm:pt-8 md:pb-8">
        {children}
      </main>
      <GuidePanel />
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-40 border-t bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        <Suspense fallback={<TabBarNavFallback />}>
          <TabBarNav />
        </Suspense>
      </nav>
    </div>
  );
}

const WIDTHS = {
  /** Forms and short pages: home, the match form. */
  narrow: "max-w-2xl",
  /** Tables and lists: trials, runs, eval. */
  wide: "max-w-5xl",
  /** Results with a trace panel beside them: match / replay / closer runs, feasibility. */
  full: "max-w-7xl",
} as const;

export type PageWidth = keyof typeof WIDTHS;

/** A page's content column inside the shell's frame: centred, its width variant, and the shared
 *  vertical gap between sections. */
export function Page({ width, children }: { width: PageWidth; children: ReactNode }) {
  return (
    <div className={`mx-auto flex w-full min-w-0 flex-col gap-4 ${WIDTHS[width]}`}>{children}</div>
  );
}
