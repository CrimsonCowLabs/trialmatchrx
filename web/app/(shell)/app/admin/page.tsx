import type { Metadata } from "next";

import { Page } from "@/components/AppShell";

import { AdminView } from "./admin-view";

// A plain title: a non-admin gets "Not found" here, with nothing that says what the page is.
// AdminView names the tab once the API has said you're an admin.
export const metadata: Metadata = {
  title: "TrialMatch Rx",
  robots: { index: false, follow: false }, // SPEC.md: robots may index `/` only
};

export default function AdminPage() {
  return (
    <Page width="wide">
      <AdminView />
    </Page>
  );
}
