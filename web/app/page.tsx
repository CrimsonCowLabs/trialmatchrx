import Link from "next/link";

import { OpenFeasibility } from "@/components/OpenFeasibility";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-2xl flex-col gap-4 px-4 py-6 sm:p-8">
      <h1 className="text-3xl font-semibold">TrialMatch Rx</h1>
      <p className="text-muted-foreground">
        Screen a patient against recruiting T2D/CKD trials, with every agent step in a live trace.
      </p>
      <Button render={<Link href="/match" />} nativeButton={false} className="self-start">
        Match a patient
      </Button>
      <p className="text-muted-foreground">
        Or see how many of 1,000 synthetic patients qualify for one trial, criterion by criterion.
      </p>
      <OpenFeasibility />
      <div className="flex flex-wrap gap-4 text-sm">
        <Link href="/trials" className="underline">
          Trials: every seeded trial
        </Link>
        <Link href="/runs" className="underline">
          Match runs: past matches
        </Link>
        <Link href="/eval" className="underline">
          Eval: scores against TREC expert labels
        </Link>
      </div>
    </main>
  );
}
