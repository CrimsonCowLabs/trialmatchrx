import { Suspense } from "react";

import { Page } from "@/components/AppShell";

import { CloserView } from "./closer-view";

export default function CloserRunPage() {
  return (
    <Page width="full">
      {/* The client view renders the header: it shows the run's status and patient. */}
      {/* useParams / useSearchParams suspend for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
        <CloserView />
      </Suspense>
    </Page>
  );
}
