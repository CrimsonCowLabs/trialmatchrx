// The admin page's small pieces: dates and the coloured state tags.
import type { ReactNode } from "react";

import type { BadgeTone } from "@/lib/admin";

/** "Nov 16, 2026": the day a request came in, an invite expires, an account was made. */
export const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });

/** "Nov 16, 2026, 3:04 PM": sign-ins. */
export const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

// Literal class names so Tailwind sees them; colours are the tokens in globals.css.
const TONE = {
  pending: "bg-verdict-unknown-bg text-tier-needs-info",
  muted: "bg-tier-ineligible-bg text-tier-ineligible",
  info: "bg-teal-tint text-teal-strong",
  warn: "bg-verdict-fail-bg text-verdict-fail",
  ok: "bg-verdict-pass-bg text-verdict-pass",
} as const satisfies Record<BadgeTone, string>;

export function Tag({
  tone,
  title,
  children,
}: {
  tone: BadgeTone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span
      data-slot="state-tag"
      data-tone={tone}
      title={title}
      className={`inline-flex h-6 w-fit shrink-0 items-center rounded-full px-2.5 text-xs font-medium whitespace-nowrap ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}
