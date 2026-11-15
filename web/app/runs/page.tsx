import Link from "next/link";

import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";

import { RunsView } from "./runs-view";

export default function RunsPage() {
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-4 px-4 py-6 sm:p-8">
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }]}
        title="Match runs"
        description="Past match runs, newest first. Open one to see its tiers, verdicts and trace again, or replay a finished run."
        actions={
          <Button render={<Link href="/match" />} nativeButton={false}>
            New match
          </Button>
        }
      />
      <RunsView />
    </main>
  );
}
