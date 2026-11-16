"use client";

// "Add a passkey": runs the browser's create-passkey prompt for the signed-in account and
// reports the new passkey. Used by /app/account; built to drop into the invite page (#3) once
// that page signs the new account in.
import { KeyRound } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, apiFailureMessage, errorMessage, type PasskeyInfo } from "@/lib/api";
import { passkeyAdd } from "@/lib/passkey-browser";

export function AddPasskeyButton({ onAdded }: { onAdded: (passkey: PasskeyInfo) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      onAdded(await passkeyAdd());
    } catch (err) {
      // A cancelled prompt rejects with a plain Error (PASSKEY_PROMPT_FAILED); the API with an
      // ApiError.
      setError(err instanceof ApiError ? apiFailureMessage(err) : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <Button type="button" onClick={add} disabled={busy}>
        <KeyRound aria-hidden />
        {busy ? "Waiting for your device…" : "Add a passkey"}
      </Button>
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
