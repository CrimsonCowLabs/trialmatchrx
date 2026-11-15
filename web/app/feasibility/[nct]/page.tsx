import Link from "next/link";
import { Suspense } from "react";

import { FeasibilityView } from "./feasibility-view";

export default function FeasibilityPage() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Trial feasibility</h1>
        <Link href="/" className="text-sm underline">
          Home
        </Link>
      </div>
      {/* useParams suspends for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <FeasibilityView />
      </Suspense>
    </main>
  );
}
