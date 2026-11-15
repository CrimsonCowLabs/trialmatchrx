"use client";

// The demo patients as selectable cards. Picking one only selects it; the page's own "Find
// trials" button starts the run, so the presenter controls timing.
import { cn } from "@/lib/utils";
import { DEMO_PATIENTS, type DemoPatient } from "@/lib/demo";

export function DemoPatientCards({
  selectedId,
  onSelect,
  className,
}: {
  selectedId: DemoPatient["id"] | null;
  onSelect: (p: DemoPatient) => void;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Demo patients"
      data-testid="demo-patients"
      className={cn("grid grid-cols-1 gap-2 sm:grid-cols-2", className)}
    >
      {DEMO_PATIENTS.map((p) => {
        const selected = p.id === selectedId;
        return (
          <button
            key={p.id}
            type="button"
            role="radio"
            aria-checked={selected}
            data-testid={`demo-patient-${p.id}`}
            onClick={() => onSelect(p)}
            className={cn(
              "flex min-w-0 flex-col gap-1 rounded-lg border p-3 text-left transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              selected
                ? "border-teal-strong bg-teal-selected"
                : "border-line bg-card hover:border-line-strong hover:bg-surface-sunken",
            )}
          >
            <span className="flex min-w-0 items-baseline justify-between gap-2">
              <span className="truncate font-medium text-ink">{p.name}</span>
              <span className="shrink-0 font-mono text-xs text-ink-4">
                {p.age} {p.sex}
              </span>
            </span>
            <span
              className={cn(
                "text-xs font-medium",
                selected ? "text-teal-strong" : "text-ink-3",
              )}
            >
              {p.condition}
            </span>
            <span className="text-xs text-ink-3">{p.summary}</span>
          </button>
        );
      })}
    </div>
  );
}
