// The request-access form (SPEC.md "Marketing and accounts", Request access). Pure, tested in
// access-request.test.ts. Validation and the spam handling (honeypot, 3 per hour per IP) live
// in the API; the page shows its message.
import type { AccessRequestCreate, AccessRole } from "./api.ts";

export const ACCESS_ROLES: readonly { value: AccessRole; label: string }[] = [
  { value: "sponsor", label: "Trial sponsor" },
  { value: "cro", label: "CRO" },
  { value: "site", label: "Research site" },
  { value: "other", label: "Other" },
];

/** What the form reads after a successful send (SPEC.md, word for word). */
export const ACCESS_REQUEST_SENT = "Thanks, we'll be in touch.";

/** A 422 (the API's detail is a list of field errors there, not a sentence). The browser's own
 *  checks (required, email, max length) catch nearly every case first. */
export const ACCESS_REQUEST_INVALID = "Check the fields: one is missing, too long or not valid.";

/** The `/#request-access` anchor that "Request access" links point to. */
export const REQUEST_ACCESS_ID = "request-access";

export type AccessRequestFields = {
  name: string;
  email: string;
  organization: string;
  role: AccessRole;
  message: string;
  /** The hidden honeypot field; a person never sees it, so it stays empty. */
  website: string;
};

/** The API body: fields trimmed, a blank message sent as null. */
export function toAccessRequest(fields: AccessRequestFields): AccessRequestCreate {
  return {
    name: fields.name.trim(),
    email: fields.email.trim(),
    organization: fields.organization.trim(),
    role: fields.role,
    message: fields.message.trim() || null,
    website: fields.website,
  };
}
