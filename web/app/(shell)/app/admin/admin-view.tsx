"use client";

// /app/admin (SPEC.md "Admin"): the access requests, to grant or dismiss, and the accounts,
// read-only. The API is the gatekeeper: it answers 404 to anyone not a signed-in admin, and
// then this page reads "Not found" and nothing else.
import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { NOT_FOUND, isNotFound } from "@/lib/admin";
import {
  api,
  ApiError,
  errorMessage,
} from "@/lib/api";
import { HOME_HREF } from "@/lib/nav";

import { RequestsCard } from "./requests-card";
import { UsersCard } from "./users-card";

type Loaded<T> = { data: T | null; error: string | null; status: number | null };

/** Like useLoad, but keeps the failed call's status (404 = not an admin) and can reload; the
 *  last data stays on screen while a reload is in flight. */
function useAdminLoad<T>(load: () => Promise<T>): [Loaded<T>, () => void] {
  const [n, setN] = useState(0);
  const [state, setState] = useState<Loaded<T>>({ data: null, error: null, status: null });
  useEffect(() => {
    let cancelled = false;
    load().then(
      (data) => !cancelled && setState({ data, error: null, status: null }),
      (err: unknown) =>
        !cancelled &&
        setState((s) => ({
          ...s,
          error: errorMessage(err),
          status: err instanceof ApiError ? err.status : null,
        })),
    );
    return () => {
      cancelled = true;
    };
  }, [load, n]);
  return [state, useCallback(() => setN((k) => k + 1), [])];
}

export function AdminView() {
  const [requests, reloadRequests] = useAdminLoad(api.listAccessRequests);
  const [users, reloadUsers] = useAdminLoad(api.listAdminUsers);
  const notFound = isNotFound(requests.status) || isNotFound(users.status);
  const known = requests.data !== null || users.data !== null;

  useEffect(() => {
    if (known && !notFound) document.title = "Admin · TrialMatch Rx";
  }, [known, notFound]);

  // A grant can create an account's invite, and a joined request means a new user: re-read both.
  const reload = useCallback(() => {
    reloadRequests();
    reloadUsers();
  }, [reloadRequests, reloadUsers]);

  if (notFound) {
    return (
      <div className="flex flex-col gap-2 py-12 text-center" data-testid="not-found">
        <h1 className="text-xl font-semibold tracking-tight">{NOT_FOUND}</h1>
        <p className="text-sm text-ink-3">There&apos;s no page at this address.</p>
      </div>
    );
  }
  if (!known && !requests.error && !users.error) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }
  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Home", href: HOME_HREF }]}
        title="Admin"
        description="Who asked for access, and who has an account."
      />
      <RequestsCard
        requests={requests.data}
        error={requests.error}
        onChanged={reload}
      />
      <UsersCard users={users.data} error={users.error} />
    </>
  );
}
