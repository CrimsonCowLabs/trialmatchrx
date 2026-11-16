import type { Metadata } from "next";

import { Page } from "@/components/AppShell";

import { AccountView } from "./account-view";

export const metadata: Metadata = {
  title: "Account · TrialMatch Rx",
  robots: { index: false, follow: false }, // SPEC.md: robots may index `/` only
};

export default function AccountPage() {
  return (
    <Page width="narrow">
      <AccountView />
    </Page>
  );
}
