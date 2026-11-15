import Link from "next/link";

import { OpenFeasibility } from "@/components/OpenFeasibility";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-4 p-8">
      <h1 className="text-3xl font-semibold">TrialMatch Rx</h1>
      <p className="text-muted-foreground">
        Screen a patient against recruiting T2D/CKD trials, with every agent step in a live trace.
      </p>
      <Button render={<Link href="/match" />} className="self-start">
        Match a patient
      </Button>
      <p className="text-muted-foreground">
        Or see how many of 1,000 synthetic patients qualify for one trial, criterion by criterion.
      </p>
      <OpenFeasibility />
    </main>
  );
}
