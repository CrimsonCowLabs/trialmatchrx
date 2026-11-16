// The reset-password form (`/reset/[token]`). Pure, tested in reset.test.ts. The password rules
// (12+ characters, not a common password) live in the API only; the page shows its message.

/** Why the form can't be sent yet, or null. Only the "type it twice" check happens here. */
export function resetFormProblem(password: string, confirm: string): string | null {
  if (!password || !confirm) return null;
  return password === confirm ? null : "The passwords don't match.";
}
