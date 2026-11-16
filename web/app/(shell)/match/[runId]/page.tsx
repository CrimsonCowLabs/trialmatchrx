import { Suspense } from "react";

import { Page } from "@/components/AppShell";

import { RunView } from "./run-view";

export default function MatchRunPage() {
  return (
    <Page width="full">
      {/* The client view renders the header: it shows the run's status and patient. */}
      {/* useParams suspends for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
        <RunView />
      </Suspense>
    </Page>
  );
}
