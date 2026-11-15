import Link from "next/link";

import { EvalView } from "./eval-view";

export default function EvalPage() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Eval</h1>
        <Link href="/match" className="text-sm underline">
          Match a patient
        </Link>
      </div>
      <p className="text-sm text-muted-foreground">
        TREC 2021 Clinical Trials topics against expert qrels, on a fixed sample. Relevant means
        label 2 (eligible); excluded and not-relevant trials both count as misses. Each topic
        reranks its own 20 judged trials, split about evenly across the three labels (so P@10
        tops out near 0.7), and topics short of any label are left out. Accuracy is
        eligible vs excluded on the label 1 and 2 trials: the matcher calls a trial eligible
        unless a criterion fails. Scores are not comparable with the official TREC numbers.
      </p>
      <EvalView />
    </main>
  );
}
