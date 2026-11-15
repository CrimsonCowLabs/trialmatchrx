import { Suspense } from "react";

import { PageHeader } from "@/components/PageHeader";

import { FeasibilityView } from "./feasibility-view";

export default function FeasibilityPage() {
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-4 px-4 py-6 sm:p-8">
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }, { label: "Trials", href: "/trials" }]}
        title="Trial feasibility"
      />
      {/* useParams suspends for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <FeasibilityView />
      </Suspense>
    </main>
  );
}
