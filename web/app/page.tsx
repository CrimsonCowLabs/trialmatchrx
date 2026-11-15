import { Page } from "@/components/AppShell";

import { FeasibilityCard, LatestEvalCard, MatchCard, RecentRunsCard } from "./home-view";

export default function Home() {
  return (
    <Page width="wide">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Match patients to recruiting trials, and see why.
        </h1>
        <p className="max-w-2xl text-sm text-ink-3 sm:text-base">
          Screen a patient against recruiting T2D/CKD trials, with every agent step in a live trace.
          Then run the same criteria in reverse to see which ones shrink a trial&apos;s eligible pool.
        </p>
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <MatchCard />
        <FeasibilityCard />
        <RecentRunsCard />
        <LatestEvalCard />
      </div>
    </Page>
  );
}
