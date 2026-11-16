// Unit tests for the passkey ceremonies. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { addPasskey, isSuperseded, PASSKEY_PROMPT_FAILED, signInWithPasskey } from "./passkeys.ts";

const CEREMONY = { challenge_id: "c1", options: { challenge: "abc" } };

function failWith(name: string, code?: string): Error {
  const err = new Error("prompt failed");
  err.name = name;
  return Object.assign(err, { code });
}

function signInSteps(prompt: () => Promise<string>) {
  const posted: unknown[] = [];
  return {
    posted,
    steps: {
      options: async () => CEREMONY,
      prompt: async (options: Record<string, unknown>) => {
        assert.deepEqual(options, CEREMONY.options);
        return prompt();
      },
      verify: async (body: { challenge_id: string; credential: string | null }) => {
        posted.push(body);
        return "signed in";
      },
    },
  };
}

test("a passkey sign-in posts the browser's answer with its challenge id", async () => {
  const { posted, steps } = signInSteps(async () => "credential");
  assert.equal(await signInWithPasskey(steps), "signed in");
  assert.deepEqual(posted, [{ challenge_id: "c1", credential: "credential" }]);
});

test("a cancelled or failed prompt is still reported, as a null credential", async () => {
  for (const name of ["NotAllowedError", "SecurityError", "UnknownError"]) {
    const { posted, steps } = signInSteps(async () => {
      throw failWith(name);
    });
    await signInWithPasskey(steps);
    assert.deepEqual(posted, [{ challenge_id: "c1", credential: null }], name);
  }
});

test("a superseded prompt (autofill replaced by the button) reports nothing", async () => {
  const { posted, steps } = signInSteps(async () => {
    throw failWith("AbortError", "ERROR_CEREMONY_ABORTED");
  });
  assert.equal(await signInWithPasskey(steps), null);
  assert.deepEqual(posted, []);
});

test("an autofill prompt error reports nothing, but an autofill pick is verified", async () => {
  const failed = signInSteps(async () => {
    throw failWith("NotAllowedError");
  });
  assert.equal(await signInWithPasskey(failed.steps, { autofill: true }), null);
  assert.deepEqual(failed.posted, []);

  const picked = signInSteps(async () => "credential");
  assert.equal(await signInWithPasskey(picked.steps, { autofill: true }), "signed in");
  assert.deepEqual(picked.posted, [{ challenge_id: "c1", credential: "credential" }]);
});

test("the API's refusal rejects with its message", async () => {
  const { steps } = signInSteps(async () => "credential");
  const refused = {
    ...steps,
    verify: async () => {
      throw new Error("Email or password is incorrect");
    },
  };
  await assert.rejects(signInWithPasskey(refused), /Email or password is incorrect/);
});

test("isSuperseded is only the abort, never a cancel", () => {
  assert.equal(isSuperseded(failWith("AbortError")), true);
  assert.equal(isSuperseded({ code: "ERROR_CEREMONY_ABORTED" }), true);
  assert.equal(isSuperseded(failWith("NotAllowedError")), false);
  assert.equal(isSuperseded(null), false);
  assert.equal(isSuperseded("AbortError"), false);
});

test("adding a passkey posts the new credential", async () => {
  const posted: unknown[] = [];
  const added = await addPasskey({
    options: async () => CEREMONY,
    prompt: async () => "new credential",
    verify: async (body) => {
      posted.push(body);
      return "added";
    },
  });
  assert.equal(added, "added");
  assert.deepEqual(posted, [{ challenge_id: "c1", credential: "new credential" }]);
});

test("a cancelled add says no passkey was added and doesn't reach the API", async () => {
  let verified = false;
  await assert.rejects(
    addPasskey({
      options: async () => CEREMONY,
      prompt: async () => {
        throw failWith("NotAllowedError");
      },
      verify: async () => {
        verified = true;
      },
    }),
    { message: PASSKEY_PROMPT_FAILED },
  );
  assert.equal(verified, false);
});
