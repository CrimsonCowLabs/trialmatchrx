import { Page } from "@/components/AppShell";

import { EvalView } from "./eval-view";

export default function EvalPage() {
  return (
    <Page width="full">
      <EvalView />
      <section className="max-w-3xl text-xs text-ink-4" aria-labelledby="eval-method">
        <h2 id="eval-method" className="mb-1 font-medium text-ink-3">
          How it&apos;s scored
        </h2>
        <p>
          TREC 2021 Clinical Trials topics against expert qrels, on a fixed sample. Relevant means
          label 2 (eligible); excluded and not-relevant trials both count as misses. Each topic
          reranks only its own judged trials, drawn across the three labels, so P@10 can&apos;t
          reach 1, and topics short of any label are left out. Accuracy is eligible vs excluded on
          the label 1 and 2 trials: the matcher calls a trial eligible unless a criterion fails.
          Scores are not comparable with the official TREC numbers.
        </p>
      </section>
    </Page>
  );
}
