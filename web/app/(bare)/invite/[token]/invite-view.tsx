"use client";

// Accept an invite (SPEC.md "Marketing and accounts", Accounts): the page checks the link,
// shows who it's for, and the person sets a password, which creates the account and signs it
// in. An unknown, expired or used link (or an email that has an account by now) shows the
// API's message instead of the form, with a way to sign in.
import Image from "next/image";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, type InviteInfo } from "@/lib/api";
import { LOGIN_HREF } from "@/lib/auth";
import { inviteProblem, type InviteProblem } from "@/lib/invite";
import { HOME_HREF } from "@/lib/nav";

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
      {/* HACK(demo): password only for now. "Add a passkey" (#4) goes here, as another way
          to finish (SPEC.md: a passkey, a password, or both). */}
      <SetPasswordForm
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

/** Set a password and finish. The API checks the rules (12+ characters, not a common
 *  password) and says which one failed. */
function SetPasswordForm({
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvite(token, { password });
      router.replace(HOME_HREF);
    } catch (err) {
      const problem = inviteProblem(err);
      if (problem.kind === "link") {
        onLinkProblem(problem);
        return;
      }
      setError(problem.message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      {/* For password managers: save the new password under this email. */}
      <input type="email" name="email" autoComplete="username" value={email} readOnly hidden />
      <div className="flex flex-col gap-1.5">
        <label htmlFor="new-password" className="text-sm font-medium">
          Password
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
          required
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
      <Button type="submit" size="lg" className="h-10" disabled={busy || !password}>
        {busy ? "Creating your account…" : "Set password and sign in"}
      </Button>
    </form>
  );
}
