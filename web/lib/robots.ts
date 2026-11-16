// The robots.txt rules (app/robots.ts serves them). Pure, tested in marketing.test.ts.
//
// Crawlers may fetch `/` (the marketing page) and nothing behind sign-in: the app pages, /login,
// the invite and reset token pages, and the API. Those pages also keep their noindex meta. Note
// the trade-off: a crawler that obeys a Disallow never fetches the page, so it never reads that
// noindex, and the bare URL can still be indexed from links elsewhere.
import type { MetadataRoute } from "next";

import { APP_SECTIONS, LOGIN_HREF } from "./auth.ts";

export const ROBOTS_DISALLOW: readonly string[] = [
  // /app, /match, /runs, /trials, /eval, /feasibility, /closer: every signed-in page.
  ...APP_SECTIONS.map((section) => `/${section}`),
  LOGIN_HREF,
  "/invite/",
  "/reset/",
  "/api/",
];

export function robotsRules(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", allow: "/", disallow: [...ROBOTS_DISALLOW] } };
}
