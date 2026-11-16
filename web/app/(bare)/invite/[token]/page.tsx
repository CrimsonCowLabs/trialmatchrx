import type { Metadata } from "next";
import { Suspense } from "react";

import { InviteView } from "./invite-view";

export const metadata: Metadata = {
  title: "Accept your invite · TrialMatch Rx",
  robots: { index: false, follow: false }, // SPEC.md: robots may index `/` only
};

// The token is read in the client view (useParams), which suspends for request-time params.
export default function InvitePage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <Suspense fallback={<p className="text-sm text-ink-3">Checking your invite…</p>}>
        <InviteView />
      </Suspense>
    </div>
  );
}
