"use client";

// "Sign out everywhere": ends every session of the account, this browser's included, then goes
// to /login. Nothing to undo, so no confirm step.
import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, apiFailureMessage } from "@/lib/api";
import { LOGIN_HREF } from "@/lib/auth";

export function SessionsCard() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signOutEverywhere() {
    setBusy(true);
    setError(null);
    try {
      await api.logoutEverywhere();
      router.replace(LOGIN_HREF);
    } catch (err) {
      // Unlike "Sign out", stay put: the other sessions may still be live.
      setError(apiFailureMessage(err));
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sessions</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-start gap-4">
        <p className="text-sm text-ink-3">
          Signed in on a device you no longer have? Sign out everywhere ends every session,
          this one included.
        </p>
        <Button type="button" variant="outline" onClick={signOutEverywhere} disabled={busy}>
          <LogOut aria-hidden />
          {busy ? "Signing out…" : "Sign out everywhere"}
        </Button>
        {error && (
          <p className="text-sm break-words text-destructive" role="alert">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
