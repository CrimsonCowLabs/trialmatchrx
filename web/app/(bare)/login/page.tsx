import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginView } from "./login-view";

export const metadata: Metadata = {
  title: "Sign in · TrialMatch Rx",
  robots: { index: false, follow: false }, // SPEC.md: robots may index `/` only
};

// `?next=` is read in the client view (useSearchParams), so it renders under Suspense.
export default function LoginPage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <Suspense>
        <LoginView />
      </Suspense>
    </div>
  );
}
