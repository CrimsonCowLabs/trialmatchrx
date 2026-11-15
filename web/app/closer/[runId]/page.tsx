import { Suspense } from "react";

import { CloserView } from "./closer-view";

export default function CloserRunPage() {
  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-8">
      <h1 className="text-2xl font-semibold">Next steps</h1>
      {/* useParams / useSearchParams suspend for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
        <CloserView />
      </Suspense>
    </main>
  );
}
