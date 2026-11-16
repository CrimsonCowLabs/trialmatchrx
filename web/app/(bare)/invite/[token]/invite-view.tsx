"use client";

// Accept an invite (SPEC.md "Marketing and accounts", Accounts): the page checks the link,
// shows who it's for, and the person adds a passkey, sets a password, or both, which creates
// the account and signs it in. An unknown, expired or used link (or an email that has an account by now) shows the
// API's message instead of the form, with a way to sign in.
import Image from "next/image";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Check, KeyRound } from "lucide-react";
import { useEffect, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, ApiError, errorMessage, type InviteInfo, type PasskeyRegisterRequest } from "@/lib/api";
import { LOGIN_HREF } from "@/lib/auth";
import { inviteProblem, type InviteProblem } from "@/lib/invite";
import { HOME_HREF } from "@/lib/nav";
import { browserSupportsWebAuthn, passkeyForInvite } from "@/lib/passkey-browser";

/** WebAuthn support doesn't change while the page is open. */
const noChange = () => () => {};

type Loaded =
  | { state: "loading" }
  | { state: "ready"; invite: InviteInfo }
  | { state: "problem"; problem: InviteProblem };

export function InviteView() {
  const { token } = useParams<{ token: string }>();
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.getInvite(token).then(
      (invite) => !cancelled && setLoaded({ state: "ready", invite }),
      (err: unknown) =>
        !cancelled && setLoaded({ state: "problem", problem: inviteProblem(err) }),
    );
    return () => {
      cancelled = true;
    };
  }, [token, attempt]);

  if (loaded.state === "loading") {
    return <p className="text-sm text-ink-3">Checking your invite…</p>;
  }
  if (loaded.state === "problem") {
    const { problem } = loaded;
    return (
      <Frame title="Can't use this invite">
        <p className="text-sm text-destructive" role="alert" data-testid="invite-error">
          {problem.message}
        </p>
        {problem.kind === "retry" ? (
          <Button
            size="lg"
            className="h-10"
            onClick={() => {
              setLoaded({ state: "loading" });
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </Button>
        ) : (
          <Button size="lg" className="h-10" render={<Link href={LOGIN_HREF} />} nativeButton={false}>
            Go to sign in
          </Button>
        )}
      </Frame>
    );
  }
  return (
    <Frame title="Create your account">
      <p className="text-sm text-ink-3">
        You&apos;re invited as <span className="font-medium text-ink">{loaded.invite.email}</span>.
      </p>
      <CreateAccountForm
        token={token}
        email={loaded.invite.email}
        onLinkProblem={(problem) => setLoaded({ state: "problem", problem })}
      />
    </Frame>
  );
}

function Frame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex w-full max-w-sm flex-col gap-6">
      <Link
        href="/"
        className="flex items-center justify-center gap-2.5 font-semibold tracking-tight"
      >
        <Image src="/brand/icon.svg" alt="" width={28} height={28} className="shrink-0" />
        TrialMatch Rx
      </Link>
      <Card>
        <CardContent className="flex flex-col gap-5">
          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          {children}
        </CardContent>
      </Card>
    </div>
  );
}

/** Add a passkey, set a password, or both, then create the account. The passkey is made
 *  first but stored only when the account is created (the API verifies it then). The API
 *  checks the password rules (12+ characters, not a common password) and says which one
 *  failed; that refusal keeps the passkey (it's checked first, so the passkey's challenge is
 *  still unspent). After any other refusal the passkey is made again. */
function CreateAccountForm({
  token,
  email,
  onLinkProblem,
}: {
  token: string;
  email: string;
  onLinkProblem: (problem: InviteProblem) => void;
}) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [passkey, setPasskey] = useState<PasskeyRegisterRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canUsePasskeys = useSyncExternalStore(noChange, browserSupportsWebAuthn, () => false);

  async function onAddPasskey() {
    setBusy(true);
    setError(null);
    try {
      setPasskey(await passkeyForInvite(token));
    } catch (err) {
      const problem = inviteProblem(err);
      if (problem.kind === "link") return onLinkProblem(problem);
      // A cancelled prompt is a plain Error ("No passkey was added."), not an ApiError.
      setError(err instanceof ApiError ? problem.message : errorMessage(err));
    }
    setBusy(false);
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvite(token, { password: password || null, passkey });
      router.replace(HOME_HREF);
    } catch (err) {
      const problem = inviteProblem(err);
      if (problem.kind === "link") {
        onLinkProblem(problem);
        return;
      }
      setError(problem.message);
      if (problem.kind !== "password") setPasskey(null); // its challenge may be spent
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      {/* For password managers: save the new password under this email. */}
      <input type="email" name="email" autoComplete="username" value={email} readOnly hidden />
      {canUsePasskeys && (
        <>
          {passkey ? (
            <p
              className="flex items-center gap-2 text-sm font-medium text-ink"
              role="status"
              data-testid="invite-passkey-ready"
            >
              <Check aria-hidden className="size-4 text-primary" />
              Passkey ready. It&apos;s saved when you create the account.
            </p>
          ) : (
            <Button
              type="button"
              size="lg"
              className="h-10"
              onClick={onAddPasskey}
              disabled={busy}
            >
              <KeyRound aria-hidden />
              Add a passkey
            </Button>
          )}
          <div className="flex items-center gap-3 text-xs text-ink-4" aria-hidden>
            <span className="h-px flex-1 bg-line-soft" />
            {passkey ? "and a password, if you like" : "and / or set a password"}
            <span className="h-px flex-1 bg-line-soft" />
          </div>
        </>
      )}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="new-password" className="text-sm font-medium">
          Password{passkey && <span className="font-normal text-ink-3"> (optional)</span>}
        </label>
        <Input
          id="new-password"
          name="password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-describedby="password-rules"
          className="h-10"
          required={!passkey}
        />
        {/* HACK(demo): the rules restated by hand from api/app/auth/passwords.py; the API's
            message on a refused password is the one that counts. */}
        <p id="password-rules" className="text-xs text-ink-3">
          At least 12 characters. Common passwords aren&apos;t allowed.
        </p>
      </div>
      {error && (
        <p className="text-sm text-destructive" role="alert" data-testid="invite-form-error">
          {error}
        </p>
      )}
      <Button
        type="submit"
        size="lg"
        variant={canUsePasskeys && !passkey ? "outline" : "default"}
        className="h-10"
        disabled={busy || (!password && !passkey)}
      >
        {busy ? "Creating your account…" : "Create account and sign in"}
      </Button>
    </form>
  );
}
