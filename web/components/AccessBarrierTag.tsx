import { Accessibility } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { type AccessBarrier, barrierTag } from "@/lib/access-barriers";

/**
 * Shown on a criterion flagged as an access barrier (issue #53): it shuts people out for a
 * reason other than health. Neutral ink, so it never reads as a verdict colour. Renders nothing
 * without a flag, so rows can render it unconditionally.
 */
export function AccessBarrierTag({ barrier }: { barrier: AccessBarrier | null | undefined }) {
  if (!barrier) return null;
  const { label, title } = barrierTag(barrier);
  return (
    <Badge
      variant="outline"
      className="border-line-strong align-[1px] text-ink-2"
      title={title}
      data-testid="access-barrier"
      data-barrier={barrier}
    >
      <Accessibility data-icon="inline-start" aria-hidden />
      <span className="sr-only">Access barrier: </span>
      {label}
    </Badge>
  );
}
