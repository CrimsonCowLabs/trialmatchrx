// HACK(demo): `/` is a placeholder until the marketing page replaces it (SPEC.md "Marketing and
// accounts").
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { HOME_HREF } from "@/lib/nav";

export default function Landing() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 px-4 py-16 text-center">
      <h1 className="text-3xl font-semibold tracking-tight text-ink">TrialMatch Rx</h1>
      <p className="max-w-md text-ink-3">
        Match patients to recruiting clinical trials, and see why.
      </p>
      <Link href={HOME_HREF} className={buttonVariants()}>
        Open the app
      </Link>
    </div>
  );
}
