"use client";

// The accounts, newest first, read-only (SPEC.md "Admin"): disabling stays on the CLI.
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AdminUser } from "@/lib/api";
import { countNoun } from "@/lib/format";

import { Tag, when } from "./shared";

function UserRow({ user }: { user: AdminUser }) {
  return (
    <li className="flex flex-col gap-1 py-3" data-testid="admin-user">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 text-sm font-medium break-all text-ink">{user.email}</span>
        {user.is_admin && <Tag tone="info">Admin</Tag>}
        {user.disabled_at && (
          <Tag tone="warn" title={`Disabled ${when(user.disabled_at)}`}>
            Disabled
          </Tag>
        )}
      </div>
      <span className="text-xs text-ink-3">
        Created {when(user.created_at)} ·{" "}
        {user.last_login_at ? `Last sign-in ${when(user.last_login_at)}` : "Never signed in"}
      </span>
    </li>
  );
}

export function UsersCard({ users, error }: { users: AdminUser[] | null; error: string | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Users</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <p className="text-sm text-ink-3">
          {users ? `${countNoun(users.length, "account", "accounts")}, newest first.` : "Every account."}{" "}
          Disable one with <code className="font-mono text-xs">make disable-user</code>.
        </p>
        {error && (
          <p className="text-sm break-words text-destructive" role="alert">
            {error}
          </p>
        )}
        {users && users.length > 0 && (
          <ul className="divide-y divide-line-soft" data-testid="admin-users">
            {users.map((u) => (
              <UserRow key={u.id} user={u} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
