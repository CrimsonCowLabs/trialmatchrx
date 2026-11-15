import { ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/**
 * Shown on a verdict whose quotes failed verification (`Verdict.verified === false`): the judge's
 * answer was downgraded to `unknown` and a `guardrail` event in the trace says what failed.
 * Renders nothing for a verified verdict, so rows can render it unconditionally.
 */
export function UnverifiedQuoteBadge({ verified }: { verified: boolean }) {
  if (verified) return null;
  return (
    <Badge
      variant="outline"
      className="border-amber-500/50 text-amber-700 dark:text-amber-400"
      title="A quote from this verdict was not found in the trial text or the patient record, so the verdict was downgraded to unknown."
    >
      <ShieldAlert data-icon="inline-start" />
      unverified quote
    </Badge>
  );
}
