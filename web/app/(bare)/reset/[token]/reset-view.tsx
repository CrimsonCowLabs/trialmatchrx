"use client";

// Set a new password with a link from `make reset-link` (SPEC.md "Marketing and accounts").
// The API checks the link (unknown, expired, used, disabled account: each its own message) and
// the password rules; the page shows its messages as is. On success the API has ended every
// other session and signed this browser in, so the page goes to Home.
import Image from "next/image";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { LOGIN_HREF } from "@/lib/auth";
import { HOME_HREF } from "@/lib/nav";
import { confirmPasswordProblem } from "@/lib/password";

const UNREACHABLE = "Couldn't reach the server. Try again.";

function messageOf(err: unknown): string {
  return err instanceof ApiError && err.detail ? err.detail : UNREACHABLE;
}

type LinkState =
  | { state: "checking" }
  | { state: "usable"; email: string }
  | { state: "refused"; message: string };

export function ResetView() {
  const router = useRouter();
  const { token } = useParams<{ token: string }>();
  const [link, setLink] = useState<LinkState>({ state: "checking" });
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.checkResetLink(token).then(
      ({ email }) => !cancelled && setLink({ state: "usable", email }),
      (err: unknown) => !cancelled && setLink({ state: "refused", message: messageOf(err) }),
    );
    return () => {
      cancelled = true;
    };
  }, [token]);

  const mismatch = confirmPasswordProblem(password, confirm);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      await api.resetPassword({ token, password });
      router.replace(HOME_HREF);
    } catch (err) {
      // 422 is the password rules (the link still works); anything else ends the link.
      if (err instanceof ApiError && err.status !== 422 && err.detail) {
        setLink({ state: "refused", message: err.detail });
      } else {
        setError(messageOf(err));
      }
      setBusy(false);
    }
  }

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
          <h1 className="text-xl font-semibold tracking-tight text-ink">Reset password</h1>
          {link.state === "checking" && (
            <p className="text-sm text-ink-3" role="status">
              Checking your link…
            </p>
          )}
          {link.state === "refused" && (
            <p className="text-sm text-destructive" role="alert" data-testid="reset-refused">
              {link.message}
            </p>
          )}
          {link.state === "usable" && (
            <form onSubmit={onSubmit} className="flex flex-col gap-4">
              <p className="text-sm text-ink-3">
                Choose a new password for <span className="font-medium text-ink">{link.email}</span>.
                It needs at least 12 characters. This signs you out everywhere else.
              </p>
              {/* For password managers: which account this new password belongs to. */}
              <input type="hidden" name="username" autoComplete="username" value={link.email} />
              <div className="flex flex-col gap-1.5">
                <label htmlFor="password" className="text-sm font-medium">
                  New password
                </label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-10"
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="confirm" className="text-sm font-medium">
                  Type it again
                </label>
                <Input
                  id="confirm"
                  name="confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  aria-invalid={mismatch ? true : undefined}
                  className="h-10"
                  required
                />
              </div>
              {(mismatch ?? error) && (
                <p className="text-sm text-destructive" role="alert" data-testid="reset-error">
                  {mismatch ?? error}
                </p>
              )}
              <Button
                type="submit"
                size="lg"
                className="h-10"
                disabled={busy || !password || !confirm || mismatch !== null}
              >
                {busy ? "Saving…" : "Set password and sign in"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
      <p className="text-center text-sm text-ink-3">
        <Link href={LOGIN_HREF} className="link font-medium hover:underline">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}
