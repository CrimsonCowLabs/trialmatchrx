import { Suspense } from "react";

import { Page } from "@/components/AppShell";

import { FeasibilityView } from "./feasibility-view";

export default function FeasibilityPage() {
  return (
    <Page width="full">
      {/* The client view renders the header: it shows the trial's title, phase and status. */}
      {/* useParams suspends for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <FeasibilityView />
      </Suspense>
    </Page>
  );
}
