// The request-access form (SPEC.md "Marketing and accounts", Request access). Pure, tested in
// access-request.test.ts. Trimming, validation and the spam handling (honeypot, 3 per hour per
// IP) live in the API; the page shows its message.
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

/** The form's state: the API body as typed, with no role until one is chosen. `website` is the
 *  hidden honeypot field; a person never sees it, so it stays empty. */
export type AccessRequestFields = Omit<AccessRequestCreate, "role" | "message"> & {
  role: AccessRole | "";
  message: string;
};

export const EMPTY_ACCESS_REQUEST: AccessRequestFields = {
  name: "",
  email: "",
  organization: "",
  role: "",
  message: "",
  website: "",
};
