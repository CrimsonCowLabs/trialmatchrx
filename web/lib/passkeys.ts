// The two passkey ceremonies (SPEC.md "Marketing and accounts", Passkeys), as plain functions
// over three steps: ask the API for options, run the browser's WebAuthn prompt, post the
// result back. The steps are passed in, so the rules are tested without a browser
// (passkeys.test.ts); lib/passkey-browser.ts wires the real ones (@simplewebauthn/browser and
// lib/api.ts).

import type { PasskeyOptions as Ceremony } from "./api.ts";

/** The ceremony was replaced by a newer one: the login page's autofill request is aborted
 *  when the person presses the passkey button. Not an attempt, so nothing is reported. */
export function isSuperseded(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  const { name, code } = err as { name?: unknown; code?: unknown };
  return name === "AbortError" || code === "ERROR_CEREMONY_ABORTED";
}

export type SignInSteps<Credential, Result> = {
  options: () => Promise<Ceremony>;
  prompt: (options: Record<string, unknown>) => Promise<Credential>;
  verify: (body: { challenge_id: string; credential: Credential | null }) => Promise<Result>;
};

/** Sign in with a passkey. Resolves with the API's answer, or null when nothing was attempted.
 *  From the button, a cancelled or failed prompt is still posted, with `credential: null`, so
 *  it gets the same answer as any failure and counts toward the throttle; the API's 401 / 429
 *  rejects with its message. Superseded prompts, and any prompt error in `autofill` mode (a
 *  browser may reject the background request on its own, e.g. with no passkey saved, and an
 *  error on page load would read as a failed sign-in), resolve null and post nothing. */
export async function signInWithPasskey<Credential, Result>(
  steps: SignInSteps<Credential, Result>,
  { autofill = false }: { autofill?: boolean } = {},
): Promise<Result | null> {
  const { challenge_id, options } = await steps.options();
  let credential: Credential | null;
  try {
    credential = await steps.prompt(options);
  } catch (err) {
    if (autofill || isSuperseded(err)) return null;
    credential = null;
  }
  return steps.verify({ challenge_id, credential });
}

export type AddSteps<Credential, Result> = {
  options: () => Promise<Ceremony>;
  prompt: (options: Record<string, unknown>) => Promise<Credential>;
  verify: (body: { challenge_id: string; credential: Credential }) => Promise<Result>;
};

/** Shown when the browser's prompt to create a passkey was cancelled or failed. */
export const PASSKEY_PROMPT_FAILED = "No passkey was added.";

/** Create a passkey: on the account page `verify` stores it on the signed-in account; on the
 *  invite page it hands the credential on to accepting the invite. A cancelled prompt rejects
 *  with PASSKEY_PROMPT_FAILED and never reaches `verify` (adding isn't a sign-in, so there's
 *  nothing to throttle); the API's 400 rejects with its own message. */
export async function addPasskey<Credential, Result>(
  steps: AddSteps<Credential, Result>,
): Promise<Result> {
  const { challenge_id, options } = await steps.options();
  let credential: Credential;
  try {
    credential = await steps.prompt(options);
  } catch {
    throw new Error(PASSKEY_PROMPT_FAILED);
  }
  return steps.verify({ challenge_id, credential });
}
