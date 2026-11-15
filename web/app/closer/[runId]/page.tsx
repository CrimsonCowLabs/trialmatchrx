import { Suspense } from "react";

import { Page } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";

import { CloserView } from "./closer-view";

export default function CloserRunPage() {
  return (
    <Page width="full">
      <PageHeader breadcrumb={[{ label: "Home", href: "/" }]} title="Next steps" />
      {/* useParams / useSearchParams suspend for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
        <CloserView />
      </Suspense>
    </Page>
  );
}
