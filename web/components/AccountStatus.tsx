"use client";

// Who's signed in, from `/api/auth/me`: the email (a link to /app/account) and a "Sign out"
// button, or a "Sign in" link back to this page while signed out. The sidebar shows it at md
// and up; below md it's a slim row above the page, since the tab bar is full.
// HACK(demo): the signed-out state exists only because login isn't required on the app pages
// yet; "Require login everywhere" (#10) makes it unreachable.
import { LogIn, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type Me } from "@/lib/api";
import { ACCOUNT_HREF, LOGIN_HREF, loginHref } from "@/lib/auth";

type Account = { state: "loading" } | { state: "signed-in"; me: Me } | { state: "signed-out" };

function useAccount(): [Account, () => Promise<void>] {
  const router = useRouter();
  const [account, setAccount] = useState<Account>({ state: "loading" });
  useEffect(() => {
    let cancelled = false;
    api.me().then(
      (me) => !cancelled && setAccount({ state: "signed-in", me }),
      () => !cancelled && setAccount({ state: "signed-out" }),
    );
    return () => {
      cancelled = true;
    };
  }, []);
  async function signOut() {
    try {
      await api.logout();
    } catch {
      // API unreachable: the session row may survive, but the page still shows signed out.
    }
    setAccount({ state: "signed-out" });
    router.push(LOGIN_HREF);
  }
  return [account, signOut];
}

type Variant = "sidebar" | "bar";

export function AccountStatus({ variant }: { variant: Variant }) {
  const pathname = usePathname();
  const [account, signOut] = useAccount();
  if (account.state === "loading") return <div aria-hidden className={HEIGHT[variant]} />;
  if (account.state === "signed-out") {
    return (
      <div className={`flex items-center ${HEIGHT[variant]} ${JUSTIFY[variant]}`}>
        <Link
          href={loginHref(pathname)}
          className="link inline-flex items-center gap-1.5 text-sm font-medium hover:underline"
        >
          <LogIn aria-hidden className="size-4" />
          Sign in
        </Link>
      </div>
    );
  }
  const signOutButton = (
    <button
      type="button"
      onClick={signOut}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-md text-sm font-medium text-ink-2 hover:text-ink focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <LogOut aria-hidden className="size-4" />
      Sign out
    </button>
  );
  if (variant === "bar") {
    return (
      <div className={`flex min-w-0 items-center justify-end gap-3 ${HEIGHT.bar}`}>
        <Link
          href={ACCOUNT_HREF}
          className="min-w-0 truncate text-xs text-ink-3 hover:underline"
          title={`${account.me.email}: your account`}
        >
          {account.me.email}
        </Link>
        {signOutButton}
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-1.5 border-t pt-3">
      <span className="text-xs text-ink-4">Signed in as</span>
      <Link
        href={ACCOUNT_HREF}
        className="truncate text-sm font-medium text-ink hover:underline"
        title={`${account.me.email}: your account`}
      >
        {account.me.email}
      </Link>
      <div>{signOutButton}</div>
    </div>
  );
}

const HEIGHT: Record<Variant, string> = { sidebar: "min-h-11", bar: "h-8" };
const JUSTIFY: Record<Variant, string> = { sidebar: "border-t pt-3", bar: "justify-end" };
