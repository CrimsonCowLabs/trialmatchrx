// /robots.txt (SPEC.md "Marketing and accounts": robots may index `/` but not /app, /login or
// the token pages). The rules, and the trade-off with noindex, are in lib/robots.ts.
import type { MetadataRoute } from "next";

import { robotsRules } from "@/lib/robots";

export default function robots(): MetadataRoute.Robots {
  return robotsRules();
}
