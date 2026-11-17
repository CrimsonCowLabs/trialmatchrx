"use client";

// The access requests (SPEC.md "Admin"), pending first, then newest first, as the API lists
// them. Grant access (Resend invite once invited) asks first in a dialog with an optional note;
// Dismiss asks inline. What a grant did (emailed, or the link to copy) shows above the list.
import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ACCESS_ROLES } from "@/lib/access-request";
import {
  grantOutcome,
  NOTE_MAX,
  notePrefill,
  pendingNote,
  rowActions,
  stateBadge,
  visibleRequests,
} from "@/lib/admin";
import { api, apiFailureMessage, type AccessRequestAdmin, type GrantResult } from "@/lib/api";
import { countNoun } from "@/lib/format";

import { day, Tag } from "./shared";

const roleLabel = (role: AccessRequestAdmin["role"]) =>
  ACCESS_ROLES.find((r) => r.value === role)?.label ?? role;

/** Messages longer than this start clamped to three lines, with "Show more". */
const LONG_MESSAGE = 240;

type Outcome = ReturnType<typeof grantOutcome>;

function CopyLink({ link }: { link: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      setCopied(false); // no clipboard (http, permissions): the link is selectable text anyway
    }
  }
  return (
    <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
      <code
        className="min-w-0 flex-1 rounded-md bg-surface-sunken px-2.5 py-1.5 font-mono text-xs break-all text-ink select-all"
        data-testid="invite-link"
      >
        {link}
      </code>
      <Button type="button" variant="outline" size="sm" onClick={copy} className="self-start">
        {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

const OUTCOME_TONE = {
  ok: "border-verdict-pass/30 bg-verdict-pass-bg text-verdict-pass",
  warn: "border-verdict-unknown/30 bg-verdict-unknown-bg text-tier-needs-info",
  error: "border-verdict-fail/30 bg-verdict-fail-bg text-verdict-fail",
} as const satisfies Record<Outcome["tone"], string>;

function OutcomeNotice({ outcome, onDismiss }: { outcome: Outcome; onDismiss: () => void }) {
  return (
    <div
      className={`flex flex-col gap-2 rounded-lg border px-3 py-2.5 text-sm ${OUTCOME_TONE[outcome.tone]}`}
      role={outcome.tone === "error" ? "alert" : "status"}
      data-testid="grant-outcome"
      data-tone={outcome.tone}
    >
      <div className="flex items-start gap-3">
        <p className="min-w-0 flex-1 font-medium break-words">{outcome.text}</p>
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-xs font-medium underline-offset-2 hover:underline"
        >
          Close
        </button>
      </div>
      {outcome.link && <CopyLink link={outcome.link} />}
    </div>
  );
}

/** Grant access / Resend invite: an optional note (prefilled "Hi <first name>,") on top of the
 *  invite email. A native modal <dialog>: Escape and Cancel close it. A 404 / 409 shows inside
 *  it; any other answer closes it and goes to `onGranted`. */
function GrantDialog({
  request,
  resend,
  onClose,
  onGranted,
}: {
  request: AccessRequestAdmin;
  resend: boolean;
  onClose: () => void;
  onGranted: (result: GrantResult) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [note, setNote] = useState(() => notePrefill(request.name));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.grantAccessRequest(request.id, { note: note.trim() || null });
      onGranted(result);
    } catch (err) {
      setError(apiFailureMessage(err));
      setBusy(false);
    }
  }

  const titleId = `grant-title-${request.id}`;
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(e) => busy && e.preventDefault()}
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-card border border-line bg-surface p-0 text-ink shadow-lg backdrop:bg-ink/40"
      data-testid="grant-dialog"
    >
      <form
        method="dialog"
        className="flex flex-col gap-4 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          void confirm();
        }}
      >
        <div className="flex flex-col gap-1">
          <h2 id={titleId} className="text-base font-semibold">
            {resend ? "Resend invite" : "Grant access"} to {request.name}?
          </h2>
          <p className="text-sm break-words text-ink-3">
            Emails a 7-day sign-up link to {request.email}.
            {resend ? " The link sent before stops working." : ""}
          </p>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`grant-note-${request.id}`} className="text-sm font-medium">
            Personal note <span className="font-normal text-ink-4">(optional)</span>
          </label>
          <Textarea
            id={`grant-note-${request.id}`}
            value={note}
            maxLength={NOTE_MAX}
            rows={4}
            onChange={(e) => setNote(e.target.value)}
            className="max-h-64"
          />
          <span className="self-end font-mono text-xs text-ink-4 tabular-nums">
            {note.length}/{NOTE_MAX}
          </span>
        </div>
        {error && (
          <p className="text-sm break-words text-destructive" role="alert">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" disabled={busy} onClick={() => ref.current?.close()}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Sending…" : resend ? "Resend invite" : "Grant access"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}

function Message({ text }: { text: string }) {
  const long = text.length > LONG_MESSAGE;
  const [open, setOpen] = useState(false);
  return (
    <div className="flex flex-col items-start gap-1">
      <p
        className={`text-sm break-words whitespace-pre-line text-ink-2 ${long && !open ? "line-clamp-3" : ""}`}
      >
        {text}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="link text-xs font-medium"
          aria-expanded={open}
        >
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

function RequestRow({
  request,
  onGrant,
  onChanged,
}: {
  request: AccessRequestAdmin;
  onGrant: (request: AccessRequestAdmin) => void;
  onChanged: () => void;
}) {
  const [dismissing, setDismissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const badge = stateBadge(request, day);
  const note = pendingNote(request);
  const actions = rowActions(request);

  async function dismiss() {
    setBusy(true);
    setError(null);
    try {
      await api.dismissAccessRequest(request.id);
      onChanged();
    } catch (err) {
      setError(apiFailureMessage(err));
    } finally {
      setBusy(false);
      setDismissing(false);
    }
  }

  return (
    <li className="flex flex-col gap-3 py-4 md:flex-row md:gap-6" data-testid="access-request">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[0.9375rem] font-medium text-ink">{request.name}</span>
          <Tag tone={badge.tone}>{badge.label}</Tag>
          {note && (
            <span className="text-xs text-tier-needs-info" data-testid="request-note">
              {note}
            </span>
          )}
        </div>
        <p className="text-sm break-all text-ink-2">
          <a href={`mailto:${request.email}`} className="hover:underline">
            {request.email}
          </a>
        </p>
        <p className="text-xs text-ink-3">
          {request.organization} · {roleLabel(request.role)} · Received {day(request.created_at)}
        </p>
        {request.message && <Message text={request.message} />}
        {error && (
          <p className="text-sm break-words text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
      {actions !== "none" && (
        <div className="flex shrink-0 flex-wrap items-start gap-2 md:w-40 md:flex-col md:items-stretch">
          {dismissing ? (
            <div className="flex flex-wrap items-center gap-2 md:flex-col md:items-stretch" role="group">
              <span className="text-sm text-ink-2">Dismiss this request?</span>
              <Button type="button" variant="destructive" size="sm" disabled={busy} onClick={dismiss}>
                {busy ? "Dismissing…" : "Dismiss"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => setDismissing(false)}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <>
              <Button
                type="button"
                variant={actions === "grant" ? "default" : "outline"}
                size="sm"
                onClick={() => onGrant(request)}
              >
                {actions === "grant" ? "Grant access" : "Resend invite"}
              </Button>
              {actions === "grant" && (
                <Button type="button" variant="ghost" size="sm" onClick={() => setDismissing(true)}>
                  Dismiss
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}

export function RequestsCard({
  requests,
  error,
  onChanged,
}: {
  requests: AccessRequestAdmin[] | null;
  error: string | null;
  onChanged: () => void;
}) {
  const [pendingOnly, setPendingOnly] = useState(true);
  const [granting, setGranting] = useState<AccessRequestAdmin | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const shown = requests ? visibleRequests(requests, pendingOnly) : null;
  const pending = requests ? visibleRequests(requests, true).length : 0;

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-3">
        <CardTitle>Access requests</CardTitle>
        <div className="inline-flex rounded-md border border-line p-0.5 text-xs font-medium" role="group" aria-label="Show">
          {[
            { on: true, label: "Pending only" },
            { on: false, label: "All" },
          ].map(({ on, label }) => (
            <button
              key={label}
              type="button"
              aria-pressed={pendingOnly === on}
              onClick={() => setPendingOnly(on)}
              className={`h-7 rounded px-2.5 ${
                pendingOnly === on ? "bg-teal-tint text-teal-strong" : "text-ink-3 hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-ink-3">
          {requests
            ? `${countNoun(pending, "pending request", "pending requests")} of ${requests.length}.`
            : "From the request-access form on the home page."}{" "}
          Granting emails a 7-day sign-up link.
        </p>
        {outcome && <OutcomeNotice outcome={outcome} onDismiss={() => setOutcome(null)} />}
        {error && (
          <p className="text-sm break-words text-destructive" role="alert">
            {error}
          </p>
        )}
        {shown &&
          (shown.length === 0 ? (
            <p className="py-2 text-sm text-ink-4">
              {pendingOnly && requests && requests.length > 0
                ? "Nothing pending."
                : "No access requests yet."}
            </p>
          ) : (
            <ul className="divide-y divide-line-soft" data-testid="access-requests">
              {shown.map((r) => (
                <RequestRow
                  key={r.id}
                  request={r}
                  onGrant={(req) => {
                    setOutcome(null);
                    setGranting(req);
                  }}
                  onChanged={onChanged}
                />
              ))}
            </ul>
          ))}
      </CardContent>
      {granting && (
        <GrantDialog
          key={granting.id}
          request={granting}
          resend={rowActions(granting) === "resend"}
          onClose={() => setGranting(null)}
          onGranted={(result) => {
            setOutcome(grantOutcome(granting.email, result));
            setGranting(null);
            onChanged();
          }}
        />
      )}
    </Card>
  );
}
