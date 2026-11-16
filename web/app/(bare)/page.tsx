// HACK(demo): `/` is a placeholder until the marketing page replaces it (SPEC.md "Marketing and
// accounts"); only its request-access form (#8) is final, and moves into section 6 of that page.
import Link from "next/link";

import { RequestAccessForm } from "@/components/RequestAccessForm";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { REQUEST_ACCESS_ID } from "@/lib/access-request";
import { HOME_HREF } from "@/lib/nav";

export default function Landing() {
  return (
    <div className="flex flex-1 flex-col items-center gap-12 px-4 py-16">
      <div className="flex flex-col items-center gap-5 text-center">
        <h1 className="text-3xl font-semibold tracking-tight text-ink">TrialMatch Rx</h1>
        <p className="max-w-md text-ink-3">
          Match patients to recruiting clinical trials, and see why.
        </p>
        <Link href={HOME_HREF} className={buttonVariants()}>
          Open the app
        </Link>
      </div>
      <section
        id={REQUEST_ACCESS_ID}
        aria-labelledby="request-access-heading"
        className="w-full max-w-xl scroll-mt-8"
      >
        <Card>
          <CardContent className="flex flex-col gap-5">
            <div className="flex flex-col gap-1">
              <h2 id="request-access-heading" className="text-xl font-semibold tracking-tight text-ink">
                Request access
              </h2>
              <p className="text-sm text-ink-3">
                For trial sponsors, CROs and research sites. Tell us who you are and we&apos;ll
                get back to you.
              </p>
            </div>
            <RequestAccessForm />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
