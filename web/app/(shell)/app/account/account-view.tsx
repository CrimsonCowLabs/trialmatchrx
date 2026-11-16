"use client";

// /app/account (SPEC.md "Marketing and accounts"): your passkeys, when each was added and
// last used, and "Add a passkey"; set or change your password.
// HACK(demo): removing a passkey (with the can't-remove-your-last-sign-in-method rule) and "Sign
// out everywhere" are still to come in #5.
import { KeyRound } from "lucide-react";
import { useCallback, useState } from "react";

import { AddPasskeyButton } from "@/components/AddPasskeyButton";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type Me, type PasskeyInfo } from "@/lib/api";
import { HOME_HREF } from "@/lib/nav";
import { useLoad } from "@/lib/use-load";

import { PasswordCard } from "./password-card";

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

function PasskeyRow({ passkey, n }: { passkey: PasskeyInfo; n: number }) {
  return (
    <li className="flex items-start gap-3 py-3" data-testid="passkey">
      <KeyRound aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-3" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium text-ink">Passkey {n}</span>
        <span className="text-xs text-ink-3">
          Added {when(passkey.created_at)} ·{" "}
          {passkey.last_used_at ? `Last used ${when(passkey.last_used_at)}` : "Not used yet"}
        </span>
      </div>
    </li>
  );
}

export function AccountView() {
  const loaded = useLoad(api.me);
  const [changed, setChanged] = useState<Me | null>(null);
  const me = changed ?? loaded.data;
  const loadPasskeys = useCallback(() => api.listPasskeys(), []);
  const listed = useLoad(loadPasskeys);
  const [added, setAdded] = useState<PasskeyInfo[]>([]);
  const passkeys = listed.data ? [...listed.data, ...added] : null;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Home", href: HOME_HREF }]}
        title="Account"
        description={me ? <p>Signed in as {me.email}</p> : null}
      />
      <Card>
        <CardHeader>
          <CardTitle>Passkeys</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p className="text-sm text-ink-3">
            Sign in with your device&apos;s fingerprint, face or PIN instead of a password.
          </p>
          {listed.error && (
            <p className="text-sm break-words text-destructive" role="alert">
              {listed.error}
            </p>
          )}
          {passkeys &&
            (passkeys.length === 0 ? (
              <p className="text-sm text-ink-4">No passkeys yet.</p>
            ) : (
              <ul className="divide-y divide-line-soft" data-testid="passkeys">
                {passkeys.map((p, i) => (
                  <PasskeyRow key={p.id} passkey={p} n={i + 1} />
                ))}
              </ul>
            ))}
          <AddPasskeyButton onAdded={(p) => setAdded((a) => [...a, p])} />
        </CardContent>
      </Card>
      {me && <PasswordCard me={me} onChanged={setChanged} />}
    </>
  );
}
