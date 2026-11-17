// The public marketing page at `/` (SPEC.md "Marketing and accounts"): its copy, config and the
// pure state behind the video and award sections. Tested in marketing.test.ts.
//
// The three config values below (video ID, results link, photos) are constants on purpose: a
// change is an edit plus a deploy (user decision, logged with the marketing plan).
import type { Metadata } from "next";

import { REQUEST_ACCESS_ID } from "./access-request.ts";
import { LOGIN_HREF } from "./auth.ts";

// The demo video's YouTube ID (https://youtu.be/9DqMOuje33I). Set it to null and the poster reads
// "Demo video coming soon".
export const DEMO_VIDEO_ID: string | null = "9DqMOuje33I";

// HACK(demo): set once HackRx 2026 publishes its results page, along with the photos (static
// files in web/public/award/). The award section is hidden until both are set.
export const AWARD_RESULTS_URL: string | null = null;
export const AWARD_PHOTOS: readonly AwardPhoto[] = [];

/** The award, in the ticket's words: the award section's title and the OG description. */
export const AWARD_TITLE = "Winner: Best Interdisciplinary Hack, HackRx 2026, by SacHacks";
/** Where the award links until a results page exists (SPEC.md). */
export const AWARD_LINK = "https://sachacks.io";

/** Where the hero's award tape and eyebrow link: the results page once there is one,
 *  sachacks.io until then. */
export function awardHref(resultsUrl: string | null): string {
  return resultsUrl || AWARD_LINK;
}

/** The hero's two CTAs: the request-access form further down this page, and sign-in. */
export const HERO_LINKS = {
  requestAccess: `#${REQUEST_ACCESS_ID}`,
  signIn: LOGIN_HREF,
} as const;

/** The prod origin, so the OG image URL is absolute (SPEC.md: the passkey domain). */
export const SITE_URL = "https://tmrx.crimsoncowlabs.com";

export interface ImageFile {
  src: string;
  width: number;
  height: number;
}

/** `src` is a static file under public/award/, e.g. "/award/stage.jpg". */
export interface AwardPhoto extends ImageFile {
  alt: string;
}

/** A capture of the app at desktop width, and the same view at 390px for phones. */
export interface MomentScreenshot extends ImageFile {
  alt: string;
  mobile: ImageFile;
}

export interface Moment {
  name: "Match" | "Closer" | "Feasibility" | "Proof";
  heading: string;
  screenshot: MomentScreenshot;
}

/** The ticket's approved copy, word for word, plus the spec's trust lines. */
export const MARKETING_COPY = {
  headline: "Find the patients your trial is missing.",
  // The hero follows the design handoff hero-3b (user decision; its copy is final). Its award
  // wording replaces the ticket's single badge string in the hero.
  hero: {
    /** The magenta award tape, separated by stars. */
    tape: ["Winner", "Best Interdisciplinary Hack", "HackRx 2026", "SACHACKS.IO"],
    eyebrowTag: "Award-winning",
    eyebrowText: "Best Interdisciplinary Hack, HackRx 2026, by SacHacks",
    /** The headline in order; `accent` parts are in the hero's teal. */
    headline: [
      { text: "Find the " },
      { text: "patients", accent: true },
      { text: " your trial is " },
      { text: "missing.", accent: true },
    ] as { text: string; accent?: boolean }[],
    requestAccess: "Request access",
    signIn: "Sign in",
  },
  subhead:
    "TrialMatch Rx screens a patient against every recruiting trial nearby, rule by rule, and shows its work. Every verdict quotes the trial and the patient's own record.",
  // SPEC.md's four moments, one approved line each, in the demo script's order (Match, then
  // the Closer's "Next steps" on the PAH card, then Feasibility); Proof closes.
  moments: [
    {
      name: "Match",
      heading: "Screen in minutes, not hours.",
      screenshot: {
        src: "/moments/match.webp",
        alt: "A match run for a synthetic patient with pulmonary fibrosis: trials sorted into likely eligible, needs info and ineligible, with one trial open showing each criterion's verdict, the patient's quoted evidence, and the unknowns still to check.",
        width: 1558,
        height: 1264,
        mobile: { src: "/moments/match-mobile.webp", width: 780, height: 1200 },
      },
    },
    {
      name: "Closer",
      heading: "Unknowns become a to-do list.",
      screenshot: {
        src: "/moments/closer.webp",
        alt: "Next steps for a synthetic patient with pulmonary arterial hypertension: one follow-up per unknown criterion, each a test to order or a question to ask, with the criterion it resolves and why.",
        width: 1304,
        height: 1200,
        mobile: { src: "/moments/closer-mobile.webp", width: 780, height: 1200 },
      },
    },
    {
      name: "Feasibility",
      heading: "See who your criteria shut out.",
      screenshot: {
        src: "/moments/feasibility.webp",
        alt: "Cohort feasibility for a trial in adults with obesity and type 2 diabetes: how many of 1,000 synthetic patients pass every rule, the biggest blocker and how many patients dropping it would add, and a waterfall of the criteria with a slider on each threshold.",
        width: 1600,
        height: 621,
        mobile: { src: "/moments/feasibility-mobile.webp", width: 780, height: 1200 },
      },
    },
    {
      name: "Proof",
      heading: "Check it, don't trust it.",
      screenshot: {
        src: "/moments/proof.webp",
        alt: "An exclusion verdict, FEV1/FVC 0.66 below 0.7, next to the trace event that produced it: a code rule, with its output and the quoted evidence.",
        width: 1600,
        height: 770,
        mobile: { src: "/moments/proof-mobile.webp", width: 780, height: 1200 },
      },
    },
  ] satisfies readonly Moment[],
  trust: [
    "Every verdict quotes the trial and the patient.",
    "Numeric rules are checked by code.",
    "Invented quotes are caught and marked unknown.",
    "All data is synthetic.",
  ],
  requestAccess: "Bring TrialMatch Rx to your trial.",
  // From the request-access ticket (#8), kept from the `/` placeholder.
  requestAccessNote:
    "For trial sponsors, CROs and research sites. Tell us who you are and we'll get back to you.",
  awardResultsLink: "See the HackRx 2026 results",
  footer: "© 2026 Crimson Cow Labs · Synthetic data only",
} as const;

export const MARKETING_METADATA: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "TrialMatch Rx · Find the patients your trial is missing",
  description:
    "TrialMatch Rx screens a patient against every recruiting trial nearby, rule by rule, and quotes the trial and the patient's own record for every verdict. For trial sponsors and CROs.",
  openGraph: {
    type: "website",
    siteName: "TrialMatch Rx",
    title: "Find the patients your trial is missing.",
    description: `Every verdict quotes the trial and the patient's own record. ${AWARD_TITLE}.`,
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "TrialMatch Rx" }],
  },
  twitter: { card: "summary_large_image" },
  // SPEC.md: robots may index `/` but not the app, /login or the token pages (those are noindex).
  robots: { index: true, follow: true },
};

export type DemoVideoState =
  | { kind: "soon"; label: string }
  | { kind: "ready"; label: string; embedUrl: string };

const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;

/** The video poster's state. No ID: "coming soon". An ID: the youtube-nocookie embed, which the
 *  page loads only on click (so it autoplays). Anything else is a config mistake and throws. */
export function demoVideo(id: string | null): DemoVideoState {
  const trimmed = id?.trim() ?? "";
  if (!trimmed) return { kind: "soon", label: "Demo video coming soon" };
  if (!YOUTUBE_ID.test(trimmed)) {
    throw new Error(`DEMO_VIDEO_ID must be a YouTube video ID (11 characters), not ${id}`);
  }
  return {
    kind: "ready",
    label: "Play the demo video",
    embedUrl: `https://www.youtube-nocookie.com/embed/${trimmed}?autoplay=1&rel=0`,
  };
}

export interface AwardSection {
  resultsUrl: string;
  photos: readonly AwardPhoto[];
}

/** The award section, or null (hidden) until both the results link and photos are set. */
export function awardSection(
  resultsUrl: string | null,
  photos: readonly AwardPhoto[],
): AwardSection | null {
  for (const p of photos) {
    if (!p.src.startsWith("/award/")) {
      throw new Error(`Award photos are static files in web/public/award/, not ${p.src}`);
    }
  }
  if (!resultsUrl || photos.length === 0) return null;
  return { resultsUrl, photos };
}
