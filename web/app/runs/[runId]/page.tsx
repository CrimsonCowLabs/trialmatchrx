import Link from "next/link";
import { Suspense } from "react";

import { ReplayView } from "./replay-view";

export default function RunReplayPage() {
  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Run replay</h1>
        <Link href="/match" className="text-sm underline">
          New match
        </Link>
      </div>
      {/* useParams suspends for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
        <ReplayView />
      </Suspense>
    </main>
  );
}
