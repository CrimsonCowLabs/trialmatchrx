// The app pages' frame: the sidebar, tab bar and guide panel (AppShell). Home is /app; Match,
// Runs, Trials, Eval, Feasibility and Closer keep their paths, since route groups add no segment.
import { AppShell } from "@/components/AppShell";

export default function ShellLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
