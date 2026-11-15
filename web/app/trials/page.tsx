import { Page } from "@/components/AppShell";

import { TrialsView } from "./trials-view";

export default function TrialsPage() {
  return (
    <Page width="wide">
      {/* The client view renders the header: its description is the cache count. */}
      <TrialsView />
    </Page>
  );
}
