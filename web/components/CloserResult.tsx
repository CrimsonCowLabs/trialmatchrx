"use client";

// The closer agent's answer for one trial (design section 04): a follow-up per unknown
// criterion, the patient summary in English and Spanish side by side, and the draft email to
// the study coordinator with Copy, Open in mail and Edit draft. Two columns when the page is
// wide enough; below that, Follow-ups / Email / Summary tabs show one section at a time.
// Edit draft only changes the text on this page (nothing is saved); Copy and Open in mail use
// the edited text.
import { ClipboardCheck, Mail, PencilLine } from "lucide-react";
import { useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { CloserOutput } from "@/lib/api";
import {
  emailDraft,
  emailText,
  followupItems,
  mailtoHref,
  type EmailDraft,
  type FollowupItem,
} from "@/lib/closer";

type Section = "followups" | "email" | "summary";

const SECTION_HEADER = "flex flex-col gap-0.5 border-b border-line-soft px-4 py-4 sm:px-5";

/** Narrow pages show only the tab's section; from the two-column width every section shows. */
function shownClass(section: Section, tab: Section): string {
  return section === tab ? "" : "@max-4xl:hidden";
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
      data-testid="email-copy"
      onClick={() =>
        navigator.clipboard.writeText(text).then(
          () => setCopied(true),
          () => setCopied(false),
        )
      }
    >
      <ClipboardCheck /> {copied ? "Copied" : "Copy"}
    </Button>
  );
}

function Followups({ items, className }: { items: FollowupItem[]; className: string }) {
  return (
    <Card className={`gap-0 py-0 ${className}`} data-testid="closer-followups">
      <div className={SECTION_HEADER}>
        <h2 className="text-base font-semibold">
          Follow-ups{" "}
          <span className="ml-1 font-mono text-[0.8125rem] font-medium text-ink-4 tabular-nums">
            {items.length}
          </span>
        </h2>
        <p className="text-[0.8125rem] text-ink-4">
          One per unknown criterion: the test or question that resolves it
        </p>
      </div>
      {items.length === 0 ? (
        <p className="px-4 py-4 text-sm text-ink-4 sm:px-5">No unknown criteria to follow up.</p>
      ) : (
        <ul className="divide-y divide-line-soft">
          {items.map((f, i) => (
            <li
              // Index too: nothing in CloserOutput stops two follow-ups for one criterion.
              key={`${i}-${f.criterionId}`}
              data-testid="followup"
              className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-3.5 px-4 py-4 sm:px-5"
            >
              <span className="rounded-full bg-verdict-unknown-bg py-1 text-center text-xs font-medium text-verdict-unknown">
                {f.tag}
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <p className="text-[0.9375rem] leading-snug font-medium text-pretty">{f.action}</p>
                <p className="text-[0.8125rem] text-ink-4">
                  <span className="font-mono">{f.criterionId}</span> · {f.why}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function PatientSummary({
  summary,
  className,
}: {
  summary: CloserOutput["patient_summary"];
  className: string;
}) {
  const langs = [
    { lang: "en", title: "English", text: summary.en },
    { lang: "es", title: "Español", text: summary.es },
  ];
  return (
    <Card className={`gap-0 py-0 ${className}`} data-testid="closer-summary">
      <div className={SECTION_HEADER}>
        <h2 className="text-base font-semibold">Patient summary</h2>
      </div>
      <div className="grid divide-line-soft sm:grid-cols-2 sm:divide-x max-sm:divide-y">
        {langs.map(({ lang, title, text }) => (
          <section key={lang} lang={lang} className="flex flex-col gap-2 px-4 py-4 sm:px-5">
            <h3 className="text-[0.6875rem] font-semibold tracking-wider text-ink-4 uppercase">
              {title}
            </h3>
            <p className="text-[0.9375rem] leading-relaxed text-pretty">{text}</p>
          </section>
        ))}
      </div>
    </Card>
  );
}

function CoordinatorEmail({
  email,
  className,
}: {
  email: CloserOutput["coordinator_email"];
  className: string;
}) {
  // Local only: the edited draft lives in this component's state and is never sent anywhere.
  const [draft, setDraft] = useState<EmailDraft>(() => emailDraft(email));
  const [editing, setEditing] = useState(false);
  const set = (field: keyof EmailDraft) => (value: string) =>
    setDraft((d) => ({ ...d, [field]: value }));

  return (
    <Card className={`gap-0 py-0 ${className}`} data-testid="closer-email">
      <div className="flex items-center justify-between gap-3 border-b border-line-soft px-4 py-4 sm:px-5">
        <h2 className="text-base font-semibold">Email to the study coordinator</h2>
        <CopyButton text={emailText(draft)} />
      </div>
      {editing ? (
        <div className="flex flex-col gap-3 px-4 py-4 sm:px-5">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-4">To</span>
            <Input
              type="email"
              value={draft.to}
              onChange={(e) => set("to")(e.target.value)}
              placeholder="No contact email listed"
              className="font-mono"
              data-testid="email-to-input"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-4">Subject</span>
            <Input
              value={draft.subject}
              onChange={(e) => set("subject")(e.target.value)}
              data-testid="email-subject-input"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-4">Message</span>
            <Textarea
              value={draft.body}
              onChange={(e) => set("body")(e.target.value)}
              className="min-h-64 leading-relaxed"
              data-testid="email-body-input"
            />
          </label>
        </div>
      ) : (
        <>
          <dl className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-2 gap-y-1.5 border-b border-line-soft px-4 py-3.5 text-sm sm:px-5">
            <dt className="text-ink-4">To</dt>
            <dd className="font-mono break-all" data-testid="email-to">
              {draft.to.trim() || (
                <span className="font-sans text-ink-4">No contact email listed</span>
              )}
            </dd>
            <dt className="text-ink-4">Subject</dt>
            <dd className="font-medium" data-testid="email-subject">
              {draft.subject}
            </dd>
          </dl>
          <p
            className="px-4 py-4 text-[0.9375rem] leading-relaxed whitespace-pre-wrap text-ink-2 sm:px-5"
            data-testid="email-body"
          >
            {draft.body}
          </p>
        </>
      )}
      <div className="flex flex-wrap gap-2.5 border-t border-line-soft px-4 py-3.5 sm:px-5">
        <a
          href={mailtoHref(draft)}
          className={buttonVariants({ size: "lg", className: "px-4 max-sm:flex-1" })}
          data-testid="email-open"
        >
          <Mail /> Open in mail
        </a>
        <Button
          variant="outline"
          size="lg"
          className="px-4"
          aria-pressed={editing}
          onClick={() => setEditing((e) => !e)}
          data-testid="email-edit"
        >
          <PencilLine /> {editing ? "Done editing" : "Edit draft"}
        </Button>
      </div>
    </Card>
  );
}

export function CloserResult({ output }: { output: CloserOutput }) {
  const [tab, setTab] = useState<Section>("followups");
  const items = followupItems(output.followups);
  const tabs: { section: Section; label: string; count?: number }[] = [
    { section: "followups", label: "Follow-ups", count: items.length },
    { section: "email", label: "Email" },
    { section: "summary", label: "Summary" },
  ];

  return (
    <div className="@container flex flex-col gap-4" data-testid="closer-result">
      <div
        role="tablist"
        aria-label="Next steps section"
        className="flex flex-wrap gap-1.5 text-sm font-medium @4xl:hidden"
      >
        {tabs.map(({ section, label, count }) => {
          const selected = section === tab;
          return (
            <button
              key={section}
              type="button"
              role="tab"
              aria-selected={selected}
              data-testid={`closer-tab-${section}`}
              onClick={() => setTab(section)}
              className={`rounded-full border px-3 py-1.5 ${selected ? "border-foreground bg-foreground text-background" : "border-line bg-surface text-ink-2"}`}
            >
              {label}
              {count !== undefined && <span className="ml-1.5 tabular-nums">{count}</span>}
            </button>
          );
        })}
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 @4xl:grid-cols-2">
        <div
          className={`flex min-w-0 flex-col gap-5 ${tab === "email" ? "@max-4xl:hidden" : ""}`}
        >
          <Followups items={items} className={shownClass("followups", tab)} />
          <PatientSummary summary={output.patient_summary} className={shownClass("summary", tab)} />
        </div>
        <CoordinatorEmail
          email={output.coordinator_email}
          className={`min-w-0 ${shownClass("email", tab)}`}
        />
      </div>
    </div>
  );
}
