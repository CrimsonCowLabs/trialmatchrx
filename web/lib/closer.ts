// Pure helpers for the closer page (CloserResult). Only a type import from ./api.ts, so
// node:test can load this file directly.
import type { CloserOutput, RunSummary } from "./api.ts";

/** "Next steps for a 61 M patient" (the match run's patient, from the run summary), else
 *  "Next steps" while the summary loads or when no patient label is known. */
export function closerTitle(summary: Partial<Pick<RunSummary, "patient_label">> | null): string {
  const label = summary?.patient_label;
  return label ? `Next steps for a ${label} patient` : "Next steps";
}

/** Whether the closer page shows its trace column: the user's Show / Hide trace choice once
 *  made, else open until the agent's answer is there to read. */
export function traceShown(choice: boolean | null, hasAnswer: boolean): boolean {
  return choice ?? !hasAnswer;
}

type CoordinatorEmail = CloserOutput["coordinator_email"];
type Followup = CloserOutput["followups"][number];

export interface FollowupItem {
  criterionId: string;
  /** "Test" = a lab or exam to order, "Ask" = a question for the patient or their clinician. */
  tag: "Test" | "Ask";
  action: string;
  why: string;
}

const TAG = { test: "Test", question: "Ask" } as const satisfies Record<
  Followup["kind"],
  FollowupItem["tag"]
>;

/** One row per follow-up, in the agent's order (trial order, per CloserOutput). */
export function followupItems(followups: Followup[]): FollowupItem[] {
  return followups.map(({ criterion_id, kind, action, why }) => ({
    criterionId: criterion_id,
    tag: TAG[kind],
    action,
    why,
  }));
}

/** The coordinator email as the page holds it: the agent's draft, or the user's edit of it. */
export interface EmailDraft {
  to: string;
  subject: string;
  body: string;
}

/** The editable draft of the agent's email; with no contact address, To starts empty. */
export function emailDraft({ to, subject, body }: CoordinatorEmail): EmailDraft {
  return { to: to ?? "", subject, body };
}

/** What Copy puts on the clipboard: To (when there is one), Subject, a blank line, the body. */
export function emailText({ to, subject, body }: EmailDraft): string {
  const head = to.trim() ? [`To: ${to.trim()}`] : [];
  return [...head, `Subject: ${subject}`, "", body].join("\n");
}

// RFC 6068: header values are percent-encoded (spaces as %20, never "+"), line breaks %0D%0A.
function encodeHeader(value: string): string {
  return encodeURIComponent(value.replace(/\r?\n/g, "\r\n"));
}

/** A mailto: link that opens the draft in the user's mail app. */
export function mailtoHref({ to, subject, body }: EmailDraft): string {
  // "@" and "," stay literal in the address part: some mail apps don't decode them there.
  const recipient = encodeURIComponent(to.trim()).replace(/%40/g, "@").replace(/%2C/g, ",");
  return `mailto:${recipient}?subject=${encodeHeader(subject)}&body=${encodeHeader(body)}`;
}
