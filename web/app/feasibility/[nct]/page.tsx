import { Suspense } from "react";

import { Page } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";

import { FeasibilityView } from "./feasibility-view";

export default function FeasibilityPage() {
  return (
    <Page width="full">
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }, { label: "Trials", href: "/trials" }]}
        title="Trial feasibility"
      />
      {/* useParams suspends for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <FeasibilityView />
      </Suspense>
    </Page>
  );
}
