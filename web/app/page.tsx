import { Page } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";

import { FeasibilityCard, LatestEvalCard, MatchCard, RecentRunsCard } from "./home-view";

export default function Home() {
  return (
    <Page width="wide">
      <PageHeader
        title="Match patients to recruiting trials, and see why."
        description={
          <p className="max-w-2xl">
            Screen a patient against recruiting T2D/CKD trials, with every agent step in a live
            trace. Then run the same criteria in reverse to see which ones shrink a trial&apos;s
            eligible pool.
          </p>
        }
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <MatchCard />
        <FeasibilityCard />
        <RecentRunsCard />
        <LatestEvalCard />
      </div>
    </Page>
  );
}
