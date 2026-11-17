// The admin page's rules (`/app/admin`, SPEC.md "Admin"). Pure, tested in admin.test.ts: what
// each access request's badge, note and actions are, the note a grant starts from, and how a
// grant's result reads. Types only from api.ts, so node:test can load this file directly.
import type { AccessRequestAdmin, GrantResult } from "./api.ts";

/** The longest note the API takes (GrantAccessRequest.note). */
export const NOTE_MAX = 2000;

/** What a non-admin (or a signed-out visitor) sees: the API's 404, nothing that says "admin". */
export const NOT_FOUND = "Not found";

/** Whether a failed admin call means "not for you": the API answers 404 to any non-admin. */
export const isNotFound = (status: number | null) => status === 404;

/** The first whitespace-separated word of a name, or "" for a blank one. */
export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? "";
}

/** The grant dialog's note to start from: "Hi Ada," (or "Hi," for a blank name). */
export function notePrefill(name: string): string {
  const first = firstName(name);
  return first ? `Hi ${first},` : "Hi,";
}

export type BadgeTone = "pending" | "muted" | "info" | "warn" | "ok";

/** A request's state badge. `date` formats the API's ISO timestamps for the page. */
export function stateBadge(
  row: Pick<AccessRequestAdmin, "state" | "invite_expires_at" | "joined_at">,
  date: (iso: string) => string,
): { label: string; tone: BadgeTone } {
  switch (row.state) {
    case "pending":
      return { label: "Pending", tone: "pending" };
    case "dismissed":
      return { label: "Dismissed", tone: "muted" };
    case "invited":
      return {
        label: row.invite_expires_at ? `Invited (expires ${date(row.invite_expires_at)})` : "Invited",
        tone: "info",
      };
    case "invite_expired":
      return { label: "Invite expired", tone: "warn" };
    case "joined":
      return { label: row.joined_at ? `Joined ${date(row.joined_at)}` : "Joined", tone: "ok" };
  }
}

/** The small note under a pending request whose email is already in: an account (granting
 *  would 409) or an invite still open (granting sends a new link). */
export function pendingNote(
  row: Pick<AccessRequestAdmin, "state" | "has_account" | "has_open_invite">,
): string | null {
  if (row.state !== "pending") return null;
  if (row.has_account) return "already has an account";
  if (row.has_open_invite) return "invite already sent";
  return null;
}

/** The buttons a request offers: Grant access + Dismiss while pending, Resend invite once
 *  invited, none after it's joined or dismissed. */
export type RowActions = "grant" | "resend" | "none";

export function rowActions(row: Pick<AccessRequestAdmin, "state">): RowActions {
  if (row.state === "pending") return "grant";
  if (row.state === "invited" || row.state === "invite_expired") return "resend";
  return "none";
}

/** How a grant's result reads: emailed; not emailed (no RESEND_API_KEY), so copy the link; or
 *  the send failed, so the error and the link to copy. The invite exists in all three. */
export function grantOutcome(
  email: string,
  result: GrantResult,
): { tone: "ok" | "warn" | "error"; text: string; link: string | null } {
  const link = result.link ?? null;
  switch (result.email_status) {
    case "sent":
      return { tone: "ok", text: `Invite emailed to ${email}`, link: null };
    case "logged":
      return { tone: "warn", text: "Email isn't configured — copy this link:", link };
    case "failed":
      return { tone: "error", text: result.error || "Couldn't send the invite email.", link };
  }
}

/** The "Pending only" filter (default on): only requests still waiting on a decision. */
export function visibleRequests<T extends Pick<AccessRequestAdmin, "state">>(
  rows: readonly T[],
  pendingOnly: boolean,
): T[] {
  return pendingOnly ? rows.filter((r) => r.state === "pending") : [...rows];
}
