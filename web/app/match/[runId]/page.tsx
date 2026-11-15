import Link from "next/link";
import { Suspense } from "react";

import { Page } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";

import { RunView } from "./run-view";

export default function MatchRunPage() {
  return (
    <Page width="full">
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }, { label: "Match runs", href: "/runs" }]}
        title="Match run"
        actions={
          <Link href="/match" className="text-sm font-medium text-teal hover:text-teal-strong">
            New match
          </Link>
        }
      />
      {/* useParams suspends for request-time params under cacheComponents */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
        <RunView />
      </Suspense>
    </Page>
  );
}
