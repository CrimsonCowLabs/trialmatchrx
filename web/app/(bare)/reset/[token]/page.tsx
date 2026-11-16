import type { Metadata } from "next";
import { Suspense } from "react";

import { ResetView } from "./reset-view";

export const metadata: Metadata = {
  title: "Reset password · TrialMatch Rx",
  robots: { index: false, follow: false }, // SPEC.md: robots may index `/` only
};

// The token is read in the client view (useParams), which suspends under cacheComponents.
export default function ResetPage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <Suspense>
        <ResetView />
      </Suspense>
    </div>
  );
}
