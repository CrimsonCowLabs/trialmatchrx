// The public marketing page at `/` (SPEC.md "Marketing and accounts"): its copy, config and the
// pure state behind the video and award sections. Tested in marketing.test.ts.
//
// The three config values below (video ID, results link, photos) are constants on purpose: a
// change is an edit plus a deploy (user decision, logged with the marketing plan).
import type { Metadata } from "next";

// HACK(demo): set once the demo video is on YouTube (the 11-character ID from its URL). Until
// then the poster reads "Demo video coming soon".
export const DEMO_VIDEO_ID: string | null = null;

// HACK(demo): set once HackRx 2026 publishes its results page, along with the photos (static
// files in web/public/award/). The award section is hidden until both are set.
export const AWARD_RESULTS_URL: string | null = null;
export const AWARD_PHOTOS: readonly AwardPhoto[] = [];

/** The badge, word for word, and where it links until a results page exists. */
export const AWARD_BADGE = "Winner: Best Interdisciplinary Hack, HackRx 2026, by SacHacks";
export const AWARD_LINK = "https://sachacks.io";

/** The prod origin, so the OG image URL is absolute (SPEC.md: the passkey domain). */
export const SITE_URL = "https://tmrx.crimsoncowlabs.com";

export interface AwardPhoto {
  /** A static file under public/award/, e.g. "/award/stage.jpg". */
  src: string;
  alt: string;
  width: number;
  height: number;
}

export interface ImageFile {
  src: string;
  width: number;
  height: number;
}

/** A capture of the app at desktop width, and the same view at 390px for phones. */
export interface MomentScreenshot extends ImageFile {
  alt: string;
  mobile: ImageFile;
}

export interface Moment {
  name: "Match" | "Feasibility" | "Proof";
  /** The approved lines; the first is the moment's heading. */
  lines: readonly string[];
  screenshot: MomentScreenshot;
}

/** The ticket's approved copy, word for word, plus the spec's trust lines. */
export const MARKETING_COPY = {
  headline: "Find the patients your trial is missing.",
  subhead:
    "TrialMatch Rx screens a patient against every recruiting trial nearby, rule by rule, and shows its work. Every verdict quotes the trial and the patient's own record.",
  // SPEC.md names three moments; the ticket approved four lines. "Unknowns become a to-do list"
  // is about the Needs info tier, which the Match screenshot shows, so Match carries two.
  moments: [
    {
      name: "Match",
      lines: ["Screen in minutes, not hours.", "Unknowns become a to-do list."],
      screenshot: {
        src: "/moments/match.webp",
        alt: "A match run for a synthetic patient with pulmonary fibrosis: trials sorted into likely eligible, needs info and ineligible, with one trial open showing each criterion's verdict, the patient's quoted evidence, and the unknowns still to check.",
        width: 1558,
        height: 1264,
        mobile: { src: "/moments/match-mobile.webp", width: 780, height: 1200 },
      },
    },
    {
      name: "Feasibility",
      lines: ["See who your criteria shut out."],
      screenshot: {
        src: "/moments/feasibility.webp",
        alt: "Cohort feasibility for a type 2 diabetes trial: how many of 1,000 synthetic patients pass every rule, the biggest blocker and how many patients dropping it would add, and a waterfall of the criteria with a slider on each threshold.",
        width: 1600,
        height: 663,
        mobile: { src: "/moments/feasibility-mobile.webp", width: 780, height: 1200 },
      },
    },
    {
      name: "Proof",
      lines: ["Check it, don't trust it."],
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
    description:
      "Every verdict quotes the trial and the patient's own record. Winner: Best Interdisciplinary Hack, HackRx 2026, by SacHacks.",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "TrialMatch Rx" }],
  },
  twitter: { card: "summary_large_image" },
  // SPEC.md: robots may index `/` but not the app, /login or the token pages (those are noindex).
  robots: { index: true, follow: true },
};

export type DemoVideo =
  | { kind: "soon"; label: string }
  | { kind: "ready"; label: string; embedUrl: string };

const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;

/** The video poster's state. No ID: "coming soon". An ID: the youtube-nocookie embed, which the
 *  page loads only on click (so it autoplays). Anything else is a config mistake and throws. */
export function demoVideo(id: string | null): DemoVideo {
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
