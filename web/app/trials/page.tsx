import Link from "next/link";

import { Page } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";

import { TrialsView } from "./trials-view";

export default function TrialsPage() {
  return (
    <Page width="wide">
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }]}
        title="Trials"
        description="Every trial in the local trials cache (the pool a match searches), read without calling ClinicalTrials.gov. Open one to see how many synthetic patients qualify."
        actions={
          <Link href="/runs" className="text-sm font-medium text-teal hover:text-teal-strong">
            Match runs
          </Link>
        }
      />
      <TrialsView />
    </Page>
  );
}
