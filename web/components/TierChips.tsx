// A run's match counts as three chips, likely / needs info / ineligible, in tier order.
// The counts are monospaced; the whole set reads as "1 likely · 2 needs info · 4 ineligible"
// to screen readers and on hover.
import type { Tier, TierCounts } from "@/lib/api";
import { TIERS, tierChips, tierSummary } from "@/lib/browse";

// Literal class names so Tailwind sees them; colours are the tier tokens in globals.css.
const TONE = {
  likely: "bg-tier-likely-bg text-tier-likely",
  needs_info: "bg-tier-needs-info-bg text-tier-needs-info",
  ineligible: "bg-tier-ineligible-bg text-tier-ineligible",
} as const satisfies Record<Tier, string>;

export function TierChips({ counts }: { counts: TierCounts }) {
  return (
    <span
      data-slot="tier-chips"
      role="img"
      aria-label={tierSummary(counts)}
      title={tierSummary(counts)}
      className="inline-flex items-center gap-1.5"
    >
      {tierChips(counts).map(({ tier, count }) => (
        <span
          key={tier}
          data-tier={tier}
          className={`inline-flex h-6 min-w-7 items-center justify-center rounded-[5px] px-2 font-mono text-xs font-medium tabular-nums ${TONE[tier]}`}
        >
          {count}
        </span>
      ))}
    </span>
  );
}

/** The key under a table of tier chips. */
export function TierLegend() {
  return (
    <span className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-4">
      {TIERS.map(({ tier, label }) => (
        <span key={tier} className="flex items-center gap-1.5">
          <span aria-hidden className={`size-2.5 rounded-[3px] border border-current ${TONE[tier]}`} />
          {label}
        </span>
      ))}
    </span>
  );
}
