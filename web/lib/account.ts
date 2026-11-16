// The account page's rules (`/app/account`). Pure, tested in account.test.ts. The API enforces
// the same rule (409 on DELETE /api/auth/passkeys/{id}); this lets the page explain it up front.

/** Why a passkey's Remove button is off. */
export const ONLY_SIGN_IN_METHOD =
  "This passkey is your only way to sign in. Set a password or add another passkey before removing it.";

/** Why a passkey can't be removed, or null: an account must keep a password or a passkey. */
export function removePasskeyBlocked({
  hasPassword,
  passkeys,
}: {
  hasPassword: boolean;
  passkeys: number;
}): string | null {
  return !hasPassword && passkeys <= 1 ? ONLY_SIGN_IN_METHOD : null;
}
