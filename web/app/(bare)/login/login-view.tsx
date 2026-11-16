"use client";

// The sign-in form (SPEC.md "Marketing and accounts", Login): email + password, "Request
// access" and "Forgot password?". The API decides every failure's message ("Email or password
// is incorrect", or "Try again in a few minutes" once throttled); the page shows it as is.
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { FORGOT_PASSWORD_MESSAGE, safeNextPath } from "@/lib/auth";
import { HOME_HREF } from "@/lib/nav";

export function LoginView() {
  const router = useRouter();
  const next = safeNextPath(useSearchParams().get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForgot, setShowForgot] = useState(false);

  // Already signed in: there's nothing to do here.
  useEffect(() => {
    let cancelled = false;
    api.me().then(
      () => !cancelled && router.replace(HOME_HREF),
      () => {}, // 401 (signed out) or API down: stay on the form
    );
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login({ email, password });
      router.replace(next);
    } catch (err) {
      setError(
        err instanceof ApiError && err.detail
          ? err.detail
          : "Couldn't reach the server. Try again.",
      );
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
          {/* HACK(demo): password only for now. "Sign in with a passkey" (#4) goes here, above
              the form, as the primary button (SPEC.md). */}
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="email" className="text-sm font-medium">
                Email
              </label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="username"
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
            <Button type="submit" size="lg" className="h-10" disabled={busy || !email || !password}>
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
