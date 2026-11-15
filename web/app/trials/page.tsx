import Link from "next/link";

import { TrialsView } from "./trials-view";

export default function TrialsPage() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Trials</h1>
        <Link href="/runs" className="text-sm underline">
          Match runs
        </Link>
      </div>
      <p className="text-sm text-muted-foreground">
        Every trial in the local trials cache (the pool a match searches), read without calling
        ClinicalTrials.gov. Open one to see how many synthetic patients qualify.
      </p>
      <TrialsView />
    </main>
  );
}
