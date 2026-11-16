// Unit tests for the account page's rules. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { ONLY_SIGN_IN_METHOD, removePasskeyBlocked } from "./account.ts";

test("a passkey-only account can't remove its only passkey", () => {
  assert.equal(removePasskeyBlocked({ hasPassword: false, passkeys: 1 }), ONLY_SIGN_IN_METHOD);
});

test("with a password, or another passkey, any passkey can go", () => {
  assert.equal(removePasskeyBlocked({ hasPassword: true, passkeys: 1 }), null);
  assert.equal(removePasskeyBlocked({ hasPassword: false, passkeys: 2 }), null);
});

test("the reason says what to do instead", () => {
  assert.match(ONLY_SIGN_IN_METHOD, /only way to sign in/);
  assert.match(ONLY_SIGN_IN_METHOD, /Set a password or add another passkey/);
});
