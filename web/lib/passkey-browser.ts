"use client";

// The passkey ceremonies (lib/passkeys.ts) wired to the real browser prompt
// (@simplewebauthn/browser) and the API. Import these from pages and components.
import {
  browserSupportsWebAuthn,
  browserSupportsWebAuthnAutofill,
  startAuthentication,
  startRegistration,
  WebAuthnAbortService,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";

import { api, type Me, type PasskeyInfo, type PasskeyRegisterRequest } from "./api";
import { addPasskey, signInWithPasskey } from "./passkeys";

export { browserSupportsWebAuthn, browserSupportsWebAuthnAutofill, WebAuthnAbortService };

/** Sign in with a passkey: `autofill` waits for the person to pick one from the email field's
 *  suggestions (conditional mediation) instead of opening the prompt now. Null when the
 *  request was superseded or (autofill) the browser rejected it on its own; rejects with an
 *  ApiError on any failed attempt. */
export function passkeySignIn({ autofill }: { autofill: boolean }): Promise<Me | null> {
  const steps = {
    options: api.passkeyLoginOptions,
    prompt: (options: Record<string, unknown>) =>
      startAuthentication({
        // py_webauthn writes the same JSON shape @simplewebauthn/server would.
        optionsJSON: options as unknown as PublicKeyCredentialRequestOptionsJSON,
        useBrowserAutofill: autofill,
      }),
    verify: ({ challenge_id, credential }: { challenge_id: string; credential: unknown }) =>
      api.passkeyLoginVerify({
        challenge_id,
        credential: credential as Record<string, unknown> | null,
      }),
  };
  return signInWithPasskey(steps, { autofill });
}

const createPasskey = (options: Record<string, unknown>) =>
  startRegistration({ optionsJSON: options as unknown as PublicKeyCredentialCreationOptionsJSON });

/** Add a passkey to the signed-in account (the account page). */
export function passkeyAdd(): Promise<PasskeyInfo> {
  return addPasskey({
    options: api.passkeyRegisterOptions,
    prompt: createPasskey,
    verify: ({ challenge_id, credential }) =>
      api.passkeyRegisterVerify({
        challenge_id,
        credential: credential as unknown as Record<string, unknown>,
      }),
  });
}

/** Create a passkey for the account an invite will create. Nothing is stored yet: the result
 *  goes to `acceptInvite` as `passkey`, which verifies it and creates the account with it. */
export function passkeyForInvite(token: string): Promise<PasskeyRegisterRequest> {
  return addPasskey({
    options: () => api.invitePasskeyOptions(token),
    prompt: createPasskey,
    verify: async ({ challenge_id, credential }) => ({
      challenge_id,
      credential: credential as unknown as Record<string, unknown>,
    }),
  });
}
