"use client";

// /app/account (SPEC.md "Marketing and accounts"): your passkeys, when each was added and
// last used, add or remove them; set or change your password; "Sign out everywhere". You can't
// remove your last way to sign in: the Remove button is off and says why (the API refuses it
// too).
import { KeyRound } from "lucide-react";
import { useCallback, useState } from "react";

import { AddPasskeyButton } from "@/components/AddPasskeyButton";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { removePasskeyBlocked } from "@/lib/account";
import { api, apiFailureMessage, type Me, type PasskeyInfo } from "@/lib/api";
import { HOME_HREF } from "@/lib/nav";
import { useLoad } from "@/lib/use-load";

import { PasswordCard } from "./password-card";
import { SessionsCard } from "./sessions-card";

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

function PasskeyRow({
  passkey,
  n,
  blocked,
  onRemoved,
}: {
  passkey: PasskeyInfo;
  n: number;
  blocked: boolean;
  onRemoved: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.removePasskey(passkey.id);
      onRemoved();
    } catch (err) {
      setError(apiFailureMessage(err));
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <li className="flex flex-col gap-2 py-3" data-testid="passkey">
      <div className="flex items-start gap-3">
        <KeyRound aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-3" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-sm font-medium text-ink">Passkey {n}</span>
          <span className="text-xs text-ink-3">
            Added {when(passkey.created_at)} ·{" "}
            {passkey.last_used_at ? `Last used ${when(passkey.last_used_at)}` : "Not used yet"}
          </span>
        </div>
        {!confirming && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={blocked}
            aria-describedby={blocked ? "only-sign-in-method" : undefined}
            onClick={() => setConfirming(true)}
          >
            Remove
          </Button>
        )}
      </div>
      {confirming && (
        <div className="flex flex-wrap items-center gap-2 pl-7" role="group">
          <span className="text-sm text-ink-2">Remove Passkey {n}?</span>
          <Button type="button" variant="destructive" size="sm" disabled={busy} onClick={remove}>
            {busy ? "Removing…" : "Remove"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => setConfirming(false)}
          >
            Cancel
          </Button>
        </div>
      )}
      {error && (
        <p className="pl-7 text-sm break-words text-destructive" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

export function AccountView() {
  const loadedMe = useLoad(api.me);
  const [changedMe, setChangedMe] = useState<Me | null>(null);
  const me = changedMe ?? loadedMe.data;

  const loadPasskeys = useCallback(() => api.listPasskeys(), []);
  const listed = useLoad(loadPasskeys);
  const [added, setAdded] = useState<PasskeyInfo[]>([]);
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set());
  const passkeys = listed.data
    ? [...listed.data, ...added].filter((p) => !removed.has(p.id))
    : null;

  const blocked =
    me && passkeys
      ? removePasskeyBlocked({ hasPassword: me.has_password, passkeys: passkeys.length })
      : null;

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
                  <PasskeyRow
                    key={p.id}
                    passkey={p}
                    n={i + 1}
                    blocked={blocked !== null}
                    onRemoved={() => setRemoved((r) => new Set(r).add(p.id))}
                  />
                ))}
              </ul>
            ))}
          {blocked && (
            <p id="only-sign-in-method" className="text-sm text-ink-3" data-testid="remove-blocked">
              {blocked}
            </p>
          )}
          <AddPasskeyButton onAdded={(p) => setAdded((a) => [...a, p])} />
        </CardContent>
      </Card>
      {me && <PasswordCard me={me} onChanged={setChangedMe} />}
      <SessionsCard />
    </>
  );
}
