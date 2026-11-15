import { Page } from "@/components/AppShell";

import { RunsView } from "./runs-view";

export default function RunsPage() {
  return (
    <Page width="wide">
      {/* The client view renders the header: its description is the run count. */}
      <RunsView />
    </Page>
  );
}
