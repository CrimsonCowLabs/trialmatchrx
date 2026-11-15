import Link from "next/link";

import { Page } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";

import { EvalView } from "./eval-view";

export default function EvalPage() {
  return (
    <Page width="wide">
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }]}
        title="Eval"
        actions={
          <Link href="/match" className="text-sm font-medium link">
            Match a patient
          </Link>
        }
      />
      <p className="text-sm text-muted-foreground">
        TREC 2021 Clinical Trials topics against expert qrels, on a fixed sample. Relevant means
        label 2 (eligible); excluded and not-relevant trials both count as misses. Each topic
        reranks its own 20 judged trials, split about evenly across the three labels (so P@10
        tops out near 0.7), and topics short of any label are left out. Accuracy is
        eligible vs excluded on the label 1 and 2 trials: the matcher calls a trial eligible
        unless a criterion fails. Scores are not comparable with the official TREC numbers.
      </p>
      <EvalView />
    </Page>
  );
}
