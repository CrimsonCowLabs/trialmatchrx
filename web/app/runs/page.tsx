import Link from "next/link";

import { RunsView } from "./runs-view";

export default function RunsPage() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Match runs</h1>
        <Link href="/match" className="text-sm underline">
          New match
        </Link>
      </div>
      <p className="text-sm text-muted-foreground">
        Past match runs, newest first. Open one to see its tiers, verdicts and trace again, or
        replay a finished run.
      </p>
      <RunsView />
    </main>
  );
}
