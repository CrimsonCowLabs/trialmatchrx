// Unit tests for the marketing page's config and state. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import {
  AWARD_LINK,
  AWARD_TITLE,
  HERO_LINKS,
  awardHref,
  MARKETING_COPY,
  MARKETING_METADATA,
  awardSection,
  demoVideo,
} from "./marketing.ts";

test("the award section's title is the ticket's wording; it links to sachacks.io", () => {
  assert.equal(AWARD_TITLE, "Winner: Best Interdisciplinary Hack, HackRx 2026, by SacHacks");
  assert.equal(AWARD_LINK, "https://sachacks.io");
});

test("the award links go to the results page once it exists, sachacks.io until then", () => {
  assert.equal(awardHref(null), "https://sachacks.io");
  assert.equal(awardHref(""), "https://sachacks.io");
  assert.equal(awardHref("https://sachacks.io/results"), "https://sachacks.io/results");
});

test("the hero is the design handoff's copy (hero-3b), word for word", () => {
  const { hero } = MARKETING_COPY;
  assert.deepEqual(hero.tape, ["Winner", "Best Interdisciplinary Hack", "HackRx 2026", "SACHACKS.IO"]);
  assert.equal(hero.eyebrowTag, "Award-winning");
  assert.equal(hero.eyebrowText, "Best Interdisciplinary Hack, HackRx 2026, by SacHacks");
  // The same award as the ticket's wording, which the award section and the OG description use.
  assert.equal(`Winner: ${hero.eyebrowText}`, AWARD_TITLE);
  // "missing." is the accented part of the headline.
  assert.equal(hero.headlineLead + hero.headlineAccent, MARKETING_COPY.headline);
  assert.equal(hero.headlineAccent, "missing.");
  assert.equal(hero.requestAccess, "Request access");
  assert.equal(hero.signIn, "Sign in");
});

test("the hero CTAs: Request access to the form on this page, Sign in to /login", () => {
  assert.equal(HERO_LINKS.requestAccess, "#request-access");
  assert.equal(HERO_LINKS.signIn, "/login");
});

test("with no video ID the poster says the demo is coming soon", () => {
  assert.deepEqual(demoVideo(null), { kind: "soon", label: "Demo video coming soon" });
  assert.deepEqual(demoVideo(""), { kind: "soon", label: "Demo video coming soon" });
  assert.deepEqual(demoVideo("   "), { kind: "soon", label: "Demo video coming soon" });
});

test("a video ID gives a youtube-nocookie embed that plays on load", () => {
  const video = demoVideo("dQw4w9WgXcQ");
  assert.equal(video.kind, "ready");
  assert.ok(video.kind === "ready");
  const url = new URL(video.embedUrl);
  assert.equal(url.origin, "https://www.youtube-nocookie.com");
  assert.equal(url.pathname, "/embed/dQw4w9WgXcQ");
  // Loaded only on click, so it should start playing at once.
  assert.equal(url.searchParams.get("autoplay"), "1");
});

test("a video ID that isn't a YouTube ID is a config mistake, not a URL to build", () => {
  assert.throws(() => demoVideo("https://youtu.be/dQw4w9WgXcQ"), /YouTube video ID/);
  assert.throws(() => demoVideo("../../x"), /YouTube video ID/);
});

const PHOTO = { src: "/award/stage.jpg", alt: "The team on stage", width: 1600, height: 1067 };

test("the award section stays hidden until both the results link and photos are set", () => {
  assert.equal(awardSection(null, []), null);
  assert.equal(awardSection("https://sachacks.io/results", []), null);
  assert.equal(awardSection(null, [PHOTO]), null);
  assert.deepEqual(awardSection("https://sachacks.io/results", [PHOTO]), {
    resultsUrl: "https://sachacks.io/results",
    photos: [PHOTO],
  });
});

test("award photos are static files under /award/", () => {
  assert.throws(
    () => awardSection("https://sachacks.io/results", [{ ...PHOTO, src: "https://x.test/a.jpg" }]),
    /public\/award/,
  );
});

test("the copy is the ticket's approved wording", () => {
  assert.equal(MARKETING_COPY.headline, "Find the patients your trial is missing.");
  assert.equal(
    MARKETING_COPY.subhead,
    "TrialMatch Rx screens a patient against every recruiting trial nearby, rule by rule, and shows its work. Every verdict quotes the trial and the patient's own record.",
  );
  assert.deepEqual(
    MARKETING_COPY.moments.flatMap((m) =>
      "unknownsLine" in m ? [m.heading, m.unknownsLine] : [m.heading],
    ),
    [
      "Screen in minutes, not hours.",
      "Unknowns become a to-do list.",
      "See who your criteria shut out.",
      "Check it, don't trust it.",
    ],
  );
  assert.deepEqual(
    MARKETING_COPY.moments.map((m) => m.name),
    ["Match", "Feasibility", "Proof"],
  );
  assert.deepEqual(MARKETING_COPY.trust, [
    "Every verdict quotes the trial and the patient.",
    "Numeric rules are checked by code.",
    "Invented quotes are caught and marked unknown.",
    "All data is synthetic.",
  ]);
  assert.equal(MARKETING_COPY.requestAccess, "Bring TrialMatch Rx to your trial.");
  assert.equal(MARKETING_COPY.footer, "© 2026 Crimson Cow Labs · Synthetic data only");
});

test("each moment has a real screenshot in public/moments, desktop and 390px", () => {
  for (const m of MARKETING_COPY.moments) {
    for (const { src } of [m.screenshot, m.screenshot.mobile]) {
      assert.match(src, /^\/moments\/[a-z-]+\.webp$/);
      const file = join(import.meta.dirname, "..", "public", src);
      assert.ok(statSync(file).size > 0, `${file} is missing`);
    }
    assert.ok(m.screenshot.alt.length > 20);
  }
});

/** Every string the page's config shows, flattened. */
function allStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(allStrings);
  if (value && typeof value === "object") return Object.values(value).flatMap(allStrings);
  return [];
}

test("no accuracy numbers: no percentages or scores anywhere in the page's copy", () => {
  for (const s of allStrings({ MARKETING_COPY, MARKETING_METADATA, AWARD_TITLE })) {
    assert.doesNotMatch(s, /\d\s*%|precision|recall|accuracy|ndcg|f1\b/i, s);
  }
});

test("the page metadata: title, description, a static OG image, and indexable", () => {
  assert.equal(MARKETING_METADATA.title, "TrialMatch Rx · Find the patients your trial is missing");
  assert.ok(typeof MARKETING_METADATA.description === "string");
  const og = MARKETING_METADATA.openGraph;
  assert.ok(og && Array.isArray(og.images));
  const [image] = og.images as { url: string; width: number; height: number }[];
  assert.equal(image.url, "/og.png");
  assert.deepEqual([image.width, image.height], [1200, 630]);
  assert.ok(statSync(join(import.meta.dirname, "..", "public", "og.png")).size > 0);
  assert.deepEqual(MARKETING_METADATA.robots, { index: true, follow: true });
});

/** The route files (page/layout .tsx) under a directory of app/. */
function routeFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return routeFiles(path);
    return /^(page|layout)\.tsx$/.test(name) ? [path] : [];
  });
}

test("robots: `/` is the only indexable page; the app, /login and the token pages are noindex", () => {
  const app = join(import.meta.dirname, "..", "app");
  const noindex = /robots:\s*\{\s*index:\s*false,\s*follow:\s*false\s*\}/;
  for (const file of [
    "(shell)/layout.tsx",
    "(bare)/login/page.tsx",
    "(bare)/invite/[token]/page.tsx",
    "(bare)/reset/[token]/page.tsx",
  ]) {
    assert.match(readFileSync(join(app, file), "utf8"), noindex, file);
  }
  // Nothing else opts back in to indexing: only the marketing page's metadata says index: true.
  for (const file of routeFiles(app)) {
    assert.doesNotMatch(readFileSync(file, "utf8"), /index:\s*true/, file);
  }
  // And there's no robots.txt: a Disallow would stop crawlers reading those pages' noindex.
  assert.throws(() => statSync(join(app, "robots.ts")));
  assert.throws(() => statSync(join(import.meta.dirname, "..", "public", "robots.txt")));
});
