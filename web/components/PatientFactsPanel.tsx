// "Patient facts": every fact the patient parse extracted, grouped (patient, conditions, labs,
// vitals, medications), each with its value / unit / date and where it came from: the verified
// quote from the input text, "from record" for a FHIR bundle, or, for a fact the parse dropped
// because its quote was not found in the input, that quote marked unverified and not used.
// Takes PatientFacts plus the parse provenance (lib/patient-facts.ts), so it doesn't assume
// the input was a note. A disclosure, closed by default, so the trials stay first.
import { FileText, ShieldAlert, ShieldCheck } from "lucide-react";

import { Card } from "@/components/ui/card";
import type { Schemas } from "@/lib/api";
import {
  factsSummary,
  patientFactRows,
  type FactQuote,
  type FactRow,
  type ParseProvenance,
} from "@/lib/patient-facts";

function Quote({ quote }: { quote: FactQuote }) {
  switch (quote.kind) {
    case "verified":
      return (
        <p className="flex min-w-0 items-start gap-1.5 text-[0.8125rem]">
          <ShieldCheck
            className="mt-0.5 size-3.5 shrink-0 text-verdict-pass"
            aria-label="Verified quote"
          />
          <span className="min-w-0 break-words text-ink-2 italic">“{quote.text}”</span>
        </p>
      );
    case "unverified":
      return (
        <p className="flex min-w-0 flex-wrap items-start gap-x-1.5 gap-y-1 text-[0.8125rem]">
          <span
            className="inline-flex shrink-0 items-center gap-1 rounded-sm border border-verdict-unknown/40 bg-verdict-unknown-bg px-1.5 text-xs font-medium text-verdict-unknown"
            title="This quote was not found in the patient input, so the fact was dropped and not used for matching. The guardrail event in the trace has the details."
          >
            <ShieldAlert className="size-3" aria-hidden />
            unverified quote · not used
          </span>
          <span className="min-w-0 break-words text-ink-4 italic line-through decoration-ink-5/60">
            {quote.text ? `“${quote.text}”` : "(empty quote)"}
          </span>
        </p>
      );
    case "record":
      return (
        <p className="flex items-center gap-1.5 text-[0.8125rem] text-ink-4">
          <FileText className="size-3.5 shrink-0" aria-hidden />
          from record
        </p>
      );
    case "none":
      return <p className="text-[0.8125rem] text-ink-5">no quote</p>;
  }
}

function Row({ row }: { row: FactRow }) {
  const dropped = row.quote.kind === "unverified";
  return (
    <li
      data-testid="patient-fact"
      data-quote={row.quote.kind}
      className="flex min-w-0 flex-col gap-0.5 border-b border-line-soft px-4 py-2.5 last:border-b-0 sm:px-5"
    >
      <p className={`min-w-0 break-words ${dropped ? "text-ink-4" : ""}`}>
        <span className="text-ink-4">{row.label}</span>{" "}
        <span className="font-medium">{row.value}</span>
        {row.date && <span className="text-ink-4"> · {row.date}</span>}
      </p>
      <Quote quote={row.quote} />
    </li>
  );
}

export function PatientFactsPanel({
  patient,
  provenance,
}: {
  patient: Schemas["PatientFacts"];
  /** From the run's `parse_patient` trace step; null until it is in the trace. */
  provenance: ParseProvenance | null;
}) {
  const rows = patientFactRows(patient, provenance);
  const groups = [...new Set(rows.map((r) => r.group))];
  return (
    <Card className="gap-0 py-0" data-testid="patient-facts-panel">
      <details className="group">
        <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3 sm:px-5 [&::-webkit-details-marker]:hidden">
          <span className="font-heading text-base font-semibold">Patient facts</span>
          <span className="text-[0.8125rem] text-ink-4">{factsSummary(rows)}</span>
          <span className="ml-auto text-[0.8125rem] font-medium link">
            <span className="group-open:hidden">Show</span>
            <span className="hidden group-open:inline">Hide</span>
          </span>
        </summary>
        {groups.map((g) => (
          <section key={g} aria-label={g} className="border-t border-line-soft">
            <h3 className="bg-surface-sunken px-4 py-1.5 text-xs font-medium tracking-wide text-ink-4 uppercase sm:px-5">
              {g}
            </h3>
            <ul>
              {rows
                .filter((r) => r.group === g)
                .map((r) => (
                  <Row key={r.key} row={r} />
                ))}
            </ul>
          </section>
        ))}
      </details>
    </Card>
  );
}
