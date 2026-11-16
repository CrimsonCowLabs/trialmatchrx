"use client";

// The request-access form (SPEC.md "Marketing and accounts", Request access): name, work
// email, organization, role and an optional message. A hidden "website" field is the honeypot:
// people never see or fill it, bots tend to, and the API then quietly stores nothing. After a
// successful send the form is replaced by "Thanks, we'll be in touch."
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ACCESS_REQUEST_INVALID,
  ACCESS_REQUEST_SENT,
  ACCESS_ROLES,
  EMPTY_ACCESS_REQUEST,
  type AccessRequestFields,
} from "@/lib/access-request";
import { api, ApiError, apiFailureMessage } from "@/lib/api";

// The API's caps (api/app/schemas.py AccessRequestCreate), so the browser stops it first.
const MAX = { name: 200, email: 320, organization: 200, message: 2000 } as const;

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 text-base outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 md:text-sm dark:bg-input/30";

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
    </div>
  );
}

export function RequestAccessForm() {
  const [fields, setFields] = useState<AccessRequestFields>(EMPTY_ACCESS_REQUEST);
  const set =
    (key: keyof AccessRequestFields) =>
    (e: { target: { value: string } }) =>
      setFields((f) => ({ ...f, [key]: e.target.value }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const { role, message } = fields;
    if (!role) return; // `required` on the select already stops this
    setBusy(true);
    setError(null);
    try {
      // The API trims every field; a blank message is stored as none.
      await api.requestAccess({ ...fields, role, message: message || null });
      setSent(true);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 422 ? ACCESS_REQUEST_INVALID : apiFailureMessage(err),
      );
    }
    setBusy(false);
  }

  if (sent) {
    return (
      <p className="py-6 text-center text-base font-medium text-ink" role="status">
        {ACCESS_REQUEST_SENT}
      </p>
    );
  }

  return (
    <form onSubmit={onSubmit} className="relative flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="ra-name" label="Name">
          <Input
            id="ra-name"
            name="name"
            autoComplete="name"
            value={fields.name}
            onChange={set("name")}
            maxLength={MAX.name}
            className="h-10"
            required
          />
        </Field>
        <Field id="ra-email" label="Work email">
          <Input
            id="ra-email"
            name="email"
            type="email"
            autoComplete="email"
            value={fields.email}
            onChange={set("email")}
            maxLength={MAX.email}
            className="h-10"
            required
          />
        </Field>
        <Field id="ra-organization" label="Organization">
          <Input
            id="ra-organization"
            name="organization"
            autoComplete="organization"
            value={fields.organization}
            onChange={set("organization")}
            maxLength={MAX.organization}
            className="h-10"
            required
          />
        </Field>
        <Field id="ra-role" label="Role">
          <select
            id="ra-role"
            name="role"
            value={fields.role}
            onChange={set("role")}
            className={SELECT_CLASS}
            required
          >
            <option value="" disabled>
              Choose one
            </option>
            {ACCESS_ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field id="ra-message" label="Message (optional)">
        <Textarea
          id="ra-message"
          name="message"
          value={fields.message}
          onChange={set("message")}
          maxLength={MAX.message}
          rows={3}
          className="min-h-20"
        />
      </Field>
      {/* The honeypot: off-screen and hidden from assistive tech, never in the tab order. */}
      <div aria-hidden className="absolute -left-[10000px] top-0 h-px w-px overflow-hidden">
        <label htmlFor="ra-website">Website</label>
        <input
          id="ra-website"
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={fields.website}
          onChange={set("website")}
        />
      </div>
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      <Button type="submit" size="lg" className="h-10 sm:self-start" disabled={busy}>
        {busy ? "Sending…" : "Request access"}
      </Button>
    </form>
  );
}
