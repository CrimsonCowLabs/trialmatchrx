// Sign-in helpers: where to go after signing in (`/login?next=`), and the link that gets you
// there. Pure, tested in auth.test.ts.
import { HOME_HREF } from "./nav.ts";

export const LOGIN_HREF = "/login";

/** Your passkeys, password and sessions. */
export const ACCOUNT_HREF = `${HOME_HREF}/account`;

/** What "Forgot password?" says (SPEC.md): the team prints a reset link (`make reset-link`). */
export const FORGOT_PASSWORD_MESSAGE = "Contact the team to reset your password.";

// Parsed against a throwaway origin: a `next` that keeps this origin is a path on this site.
const BASE = "http://next.invalid";

/** A single leading `/`, no backslashes or control characters: a path, never `//host`. */
function isPlainPath(path: string): boolean {
  return path.startsWith("/") && !path.startsWith("//") && !/[\\\u0000-\u001f\u007f]/.test(path);
}

/** The `next` path to go to after signing in, or Home. Only a path on this site is accepted
 *  (no open redirect): both what was given and what it normalizes to (dot segments resolved,
 *  so `/.//evil.example` can't turn into `//evil.example`) must be a plain path on this
 *  origin. `/login` itself falls back to Home. */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !isPlainPath(next)) return HOME_HREF;
  let url: URL;
  try {
    url = new URL(next, BASE);
  } catch {
    return HOME_HREF;
  }
  if (url.origin !== BASE) return HOME_HREF;
  if (url.pathname === LOGIN_HREF || url.pathname.startsWith(`${LOGIN_HREF}/`)) return HOME_HREF;
  const path = `${url.pathname}${url.search}${url.hash}`;
  return isPlainPath(path) ? path : HOME_HREF;
}

/** The sign-in link from `pathname`, coming back to it afterwards (Home needs no `next`). */
export function loginHref(pathname: string | null): string {
  if (!pathname || pathname === HOME_HREF || safeNextPath(pathname) !== pathname) {
    return LOGIN_HREF;
  }
  return `${LOGIN_HREF}?${new URLSearchParams({ next: pathname })}`;
}
