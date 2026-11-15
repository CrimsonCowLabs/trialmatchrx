import Link from "next/link";
import { Suspense } from "react";

import { PageHeader } from "@/components/PageHeader";

import { ReplayView } from "./replay-view";

export default function RunReplayPage() {
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-4 px-4 py-6 sm:p-8">
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }, { label: "Match runs", href: "/runs" }]}
        title="Run replay"
        actions={
          <Link href="/match" className="text-sm font-medium text-teal hover:text-teal-strong">
            New match
          </Link>
        }
      />
      {/* useParams suspends for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
        <ReplayView />
      </Suspense>
    </main>
  );
}
