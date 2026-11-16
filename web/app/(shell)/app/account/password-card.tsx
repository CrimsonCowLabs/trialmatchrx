"use client";

// Set a password (a passkey-only account) or change it (the current one is required). The
// API checks the rules and the current password and answers with the message to show; this
// form only checks that the new one was typed the same twice.
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, apiFailureMessage, type Me } from "@/lib/api";
import { confirmPasswordProblem } from "@/lib/password";

function Field({
  id,
  label,
  value,
  onChange,
  autoComplete,
  invalid,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: "current-password" | "new-password";
  invalid?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        name={id}
        type="password"
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid ? true : undefined}
        className="h-10"
        required
      />
    </div>
  );
}

export function PasswordCard({ me, onChanged }: { me: Me; onChanged: (me: Me) => void }) {
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const changing = me.has_password;
  const mismatch = confirmPasswordProblem(password, confirm);
  const ready = Boolean((!changing || current) && password && confirm && mismatch === null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const updated = await api.changePassword({
        new_password: password,
        ...(changing && { current_password: current }),
      });
      setCurrent("");
      setPassword("");
      setConfirm("");
      setDone(`${changing ? "Password changed" : "Password set"}. You're signed out everywhere else.`);
      onChanged(updated);
    } catch (err) {
      setError(apiFailureMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Password</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" data-testid="password-form">
          <p className="text-sm text-ink-3">
            {changing
              ? "Change the password you sign in with."
              : "You sign in with a passkey only. Set a password to sign in with your email too."}{" "}
            It needs at least 12 characters, and setting it signs you out everywhere else.
          </p>
          {/* For password managers: which account this password belongs to. */}
          <input type="hidden" name="username" autoComplete="username" value={me.email} />
          {changing && (
            <Field
              id="current-password"
              label="Current password"
              value={current}
              onChange={setCurrent}
              autoComplete="current-password"
            />
          )}
          <Field
            id="new-password"
            label="New password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
          />
          <Field
            id="confirm-password"
            label="Type it again"
            value={confirm}
            onChange={setConfirm}
            autoComplete="new-password"
            invalid={mismatch !== null}
          />
          {(mismatch ?? error) && (
            <p className="text-sm break-words text-destructive" role="alert">
              {mismatch ?? error}
            </p>
          )}
          {done && (
            <p className="text-sm text-status-done" role="status" data-testid="password-done">
              {done}
            </p>
          )}
          <div>
            <Button type="submit" disabled={busy || !ready}>
              {busy ? "Saving…" : changing ? "Change password" : "Set password"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
