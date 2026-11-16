// The app pages' frame: the sidebar, tab bar and guide panel (AppShell). Home is /app; Match,
// Runs, Trials, Eval, Feasibility and Closer keep their paths, since route groups add no segment.
import type { Metadata } from "next";

import { AppShell } from "@/components/AppShell";

// Every page in the group inherits it unless it sets its own robots.
export const metadata: Metadata = {
  robots: { index: false, follow: false }, // SPEC.md: robots may index `/` only
};

export default function ShellLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
