// Next.js Proxy (formerly Middleware): a signed-out visitor to an app page goes to
// /login?next=<the page>, and /login sends them back after signing in. SPEC.md "Enforcement":
// this only redirects; the API is the only gatekeeper. It checks that a session cookie is
// there, not that it's valid, so a stale cookie reaches the page, whose first API call gets a
// 401 and goes to /login from there (lib/api.ts).
import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, signInRedirect } from "@/lib/auth";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const target = signInRedirect(pathname, search, request.cookies.has(SESSION_COOKIE));
  // Resolved against nextUrl (built from the Host header Caddy passes on), not the server's
  // own listen address.
  return target ? NextResponse.redirect(new URL(target, request.nextUrl)) : NextResponse.next();
}

// The app pages only (lib/auth.ts APP_SECTIONS; a matcher must be a literal). Everything else
// stays public without running the proxy: `/`, /login, /invite/*, /reset/*, static assets and
// Next internals.
export const config = {
  matcher: [
    "/app/:path*",
    "/match/:path*",
    "/runs/:path*",
    "/trials/:path*",
    "/eval/:path*",
    "/feasibility/:path*",
    "/closer/:path*",
  ],
};
