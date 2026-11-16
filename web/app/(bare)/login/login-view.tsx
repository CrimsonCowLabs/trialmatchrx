"use client";

// The sign-in page (SPEC.md "Marketing and accounts", Login): "Sign in with a passkey" as the
// primary button, browser autofill offering saved passkeys from the email field, and the email +
// password form below, with "Request access" and "Forgot password?". The API decides every
// failure's message ("Email or password is incorrect", or "Try again in a few minutes" once
// throttled), passkey or password; the page shows it as is.
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { KeyRound } from "lucide-react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, ApiError, apiFailureMessage } from "@/lib/api";
import { FORGOT_PASSWORD_MESSAGE, safeNextPath } from "@/lib/auth";
import {
  browserSupportsWebAuthn,
  browserSupportsWebAuthnAutofill,
  passkeySignIn,
  WebAuthnAbortService,
} from "@/lib/passkey-browser";

/** WebAuthn support doesn't change while the page is open. */
const noChange = () => () => {};


export function LoginView() {
  const router = useRouter();
  const next = safeNextPath(useSearchParams().get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForgot, setShowForgot] = useState(false);
  // False on the server and in browsers without WebAuthn: then only the password form shows.
  const canUsePasskeys = useSyncExternalStore(noChange, browserSupportsWebAuthn, () => false);

  // Already signed in: there's nothing to do here, so go where you were headed.
  useEffect(() => {
    let cancelled = false;
    api.me().then(
      () => !cancelled && router.replace(next),
      () => {}, // 401 (signed out) or API down: stay on the form
    );
    return () => {
      cancelled = true;
    };
  }, [router, next]);

  // Autofill: the email field's suggestions include this site's passkeys, and picking one
  // signs in. The request waits in the background until then; the passkey button supersedes
  // it. After any failed attempt (button or an autofill pick) it's started again. Leaving the
  // page cancels it.
  const autofill = useRef({ active: false });
  const startAutofill = useCallback(() => {
    const run = { active: true };
    autofill.current = run;
    const wait = () =>
      passkeySignIn({ autofill: true }).then(
        (me) => run.active && me && router.replace(next),
        (err: unknown) => {
          if (!run.active || !(err instanceof ApiError)) return;
          setError(apiFailureMessage(err));
          wait();
        },
      );
    browserSupportsWebAuthnAutofill().then((supported) => supported && run.active && wait());
  }, [router, next]);

  useEffect(() => {
    startAutofill();
    return () => {
      autofill.current.active = false;
      WebAuthnAbortService.cancelCeremony();
    };
  }, [startAutofill]);

  async function onPasskey() {
    setBusy(true);
    setError(null);
    try {
      if (await passkeySignIn({ autofill: false })) return router.replace(next);
    } catch (err) {
      setError(apiFailureMessage(err));
      startAutofill();
    }
    setBusy(false);
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login({ email, password });
      router.replace(next);
    } catch (err) {
      setError(apiFailureMessage(err));
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
          <h1 className="text-xl font-semibold tracking-tight text-ink">Sign in</h1>
          {canUsePasskeys && (
            <>
              <Button type="button" size="lg" className="h-10" onClick={onPasskey} disabled={busy}>
                <KeyRound aria-hidden />
                Sign in with a passkey
              </Button>
              <div className="flex items-center gap-3 text-xs text-ink-4" aria-hidden>
                <span className="h-px flex-1 bg-line-soft" />
                or use your password
                <span className="h-px flex-1 bg-line-soft" />
              </div>
            </>
          )}
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="email" className="text-sm font-medium">
                Email
              </label>
              <Input
                id="email"
                name="email"
                type="email"
                // "webauthn" lets autofill offer saved passkeys here too.
                autoComplete="username webauthn"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-10"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-4">
                <label htmlFor="password" className="text-sm font-medium">
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => setShowForgot(true)}
                  aria-expanded={showForgot}
                  aria-controls="forgot-password"
                  className="link text-xs font-medium hover:underline"
                >
                  Forgot password?
                </button>
              </div>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-10"
                required
              />
              {showForgot && (
                <p id="forgot-password" className="text-xs text-ink-3" role="status">
                  {FORGOT_PASSWORD_MESSAGE}
                </p>
              )}
            </div>
            {error && (
              <p className="text-sm text-destructive" role="alert" data-testid="login-error">
                {error}
              </p>
            )}
            <Button
              type="submit"
              size="lg"
              variant={canUsePasskeys ? "outline" : "default"}
              className="h-10"
              disabled={busy || !email || !password}
            >
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
      <p className="text-center text-sm text-ink-3">
        No account?{" "}
        <Link href="/#request-access" className="link font-medium hover:underline">
          Request access
        </Link>
      </p>
    </div>
  );
}
