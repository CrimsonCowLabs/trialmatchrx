import { Suspense } from "react";

import { PageHeader } from "@/components/PageHeader";

import { CloserView } from "./closer-view";

export default function CloserRunPage() {
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-4 px-4 py-6 sm:p-8">
      <PageHeader breadcrumb={[{ label: "Home", href: "/" }]} title="Next steps" />
      {/* useParams / useSearchParams suspend for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
        <CloserView />
      </Suspense>
    </main>
  );
}
