// The invite page's helpers (SPEC.md "Marketing and accounts", Accounts). Pure, tested in
// invite.test.ts. The API decides every message; this only says where the page shows it.

/** Why the invite page can't go on:
 *  - `link`: the link is unknown, expired or used, or the email has an account by now (the
 *    API's 404 / 410 / 409). Shown as the page's error, with a way to sign in instead.
 *  - `password`: the password breaks a rule (422, as on the reset page). Shown under the
 *    form; the link still works.
 *  - `retry`: the API didn't answer as expected. Shown under the form or with a retry. */
export type InviteProblem = { kind: "link" | "password" | "retry"; message: string };

export const RETRY_MESSAGE = "Couldn't reach the server. Try again.";

const LINK_STATUSES = new Set([404, 409, 410]);

/** What a failed invite call (an ApiError, or a fetch that threw) means for the page. */
export function inviteProblem(err: unknown): InviteProblem {
  if (typeof err === "object" && err !== null && "status" in err && "detail" in err) {
    const { status, detail } = err as { status: unknown; detail: unknown };
    if (typeof detail === "string" && detail) {
      if (typeof status === "number" && LINK_STATUSES.has(status)) {
        return { kind: "link", message: detail };
      }
      if (status === 422) return { kind: "password", message: detail };
    }
  }
  return { kind: "retry", message: RETRY_MESSAGE };
}
