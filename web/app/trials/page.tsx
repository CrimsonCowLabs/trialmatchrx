import Link from "next/link";

import { PageHeader } from "@/components/PageHeader";

import { TrialsView } from "./trials-view";

export default function TrialsPage() {
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-4 px-4 py-6 sm:p-8">
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
    </main>
  );
}
