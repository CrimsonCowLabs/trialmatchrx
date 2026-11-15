import Link from "next/link";

import { Page } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";

import { RunsView } from "./runs-view";

export default function RunsPage() {
  return (
    <Page width="wide">
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
    </Page>
  );
}
