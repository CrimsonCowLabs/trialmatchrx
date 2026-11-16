// The marketing page's hero, from the claude.ai design handoff "hero-3b": a dark band with a
// rotated magenta award tape, the nav, an "Award-winning" eyebrow, the headline with
// "patients" and "missing." in teal, and pill CTAs. Colours are the hero-* and award-* tokens
// in globals.css; copy and link targets come from lib/marketing.ts.
import Image from "next/image";
import Link from "next/link";
import { Fragment } from "react";

import { AWARD_RESULTS_URL, HERO_LINKS, MARKETING_COPY, awardHref } from "@/lib/marketing";

const { hero } = MARKETING_COPY;
/** The handoff's 72px side padding on desktop; 16px gutters on a phone. */
const GUTTERS = "px-4 sm:px-8 lg:px-[72px]";
/** The hero's keyboard focus ring, teal on the dark band. */
const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-hero-accent";
const PILL = `inline-flex items-center justify-center gap-2.5 rounded-full border-2 py-[17px] text-lg ${FOCUS} focus-visible:ring-offset-2 focus-visible:ring-offset-hero`;

export function MarketingHero() {
  const award = awardHref(AWARD_RESULTS_URL);
  return (
    <section
      aria-labelledby="hero-heading"
      // The bottom margin is the light gap above the demo video (the section below keeps its own
      // padding).
      className="relative mb-20 flex min-h-svh flex-col overflow-hidden bg-hero text-hero-fg sm:mb-28"
    >
      <header>
        <AwardTape href={award} />
        <nav aria-label="Site" className={`${GUTTERS} flex items-center justify-between pt-7`}>
          <span className="flex items-center gap-3">
            <Image src="/brand/icon.svg" alt="" width={30} height={30} />
            <span className="text-lg font-semibold">TrialMatch Rx</span>
          </span>
          <Link
            href={HERO_LINKS.signIn}
            className={`rounded text-[0.9375rem] font-medium text-hero-nav hover:text-hero-fg ${FOCUS}`}
          >
            {hero.signIn}
          </Link>
        </nav>
      </header>

      <div
        className={`${GUTTERS} flex flex-1 flex-col justify-center gap-7 pt-12 pb-10 lg:pt-0`}
      >
        <a
          href={award}
          className={`flex flex-wrap items-center gap-x-3.5 gap-y-3 self-start rounded font-mono text-[0.8125rem] font-bold tracking-[0.1em] text-award-cream uppercase hover:text-hero-fg sm:text-[0.9375rem] ${FOCUS}`}
        >
          <span className="inline-flex items-center gap-2 rounded-[6px] border-2 border-hero-ink bg-award-cream px-3 py-1.5 text-award-plum shadow-[3px_3px_0_var(--award-magenta)]">
            <AwardRosette />
            {hero.eyebrowTag}
          </span>
          {hero.eyebrowText}
        </a>
        <h1
          id="hero-heading"
          className="max-w-[1000px] text-[clamp(3rem,1.6rem+5.6vw,6rem)] leading-[0.98] font-bold tracking-[-0.045em] text-balance"
        >
          {hero.headline.map((part) =>
            part.accent ? (
              <span key={part.text} className="text-hero-accent">
                {part.text}
              </span>
            ) : (
              part.text
            ),
          )}
        </h1>
        <p className="max-w-[640px] text-lg leading-[1.55] text-pretty text-hero-muted sm:text-xl">
          {MARKETING_COPY.subhead}
        </p>
        <div className="mt-1.5 flex flex-col gap-4 min-[480px]:flex-row min-[480px]:items-center min-[480px]:gap-5">
          <a
            href={HERO_LINKS.requestAccess}
            className={`${PILL} border-hero-ink bg-hero-accent px-7 font-bold text-hero-on-accent shadow-[5px_5px_0_var(--award-cream)] transition-[translate,box-shadow] duration-100 hover:shadow-[3px_3px_0_var(--award-cream)] motion-safe:hover:translate-x-0.5 motion-safe:hover:translate-y-0.5`}
          >
            {hero.requestAccess} <span aria-hidden>→</span>
          </a>
          <Link
            href={HERO_LINKS.signIn}
            className={`${PILL} border-hero-outline px-[26px] font-semibold text-hero-fg hover:border-hero-nav`}
          >
            {hero.signIn}
          </Link>
        </div>
      </div>
    </section>
  );
}

/** The full-bleed magenta strip across the top, rotated, with a slow marquee (still, and
 *  centred as in the handoff, under prefers-reduced-motion). It repeats the eyebrow's award, so it's hidden from screen readers
 *  and out of the tab order; it still links to the award for a pointer. */
function AwardTape({ href }: { href: string }) {
  const items = (copyIndex: number) =>
    // Four rounds per copy, so one copy is wider than any screen and the loop never shows a gap.
    [0, 1, 2, 3].flatMap((round) =>
      hero.tape.map((item, i) => (
        <Fragment key={`${copyIndex}-${round}-${i}`}>
          <span>{item}</span>
          <span>★</span>
        </Fragment>
      )),
    );
  return (
    <a
      href={href}
      aria-hidden
      tabIndex={-1}
      // The top margin grows with the width: rotated, the tape's right end rises by about
      // half its width x sin(1.5deg), and the section would clip it on a wide screen.
      className="-mx-5 mt-[max(18px,calc(1.31vw+6px))] flex -rotate-[1.5deg] motion-reduce:justify-center overflow-hidden border-y-[3px] border-hero-ink bg-award-magenta py-3 text-[1.125rem] font-extrabold tracking-[0.02em] whitespace-nowrap text-hero-ink uppercase italic"
    >
      {/* pr-7 matches the gap, so the second copy starts exactly half way along the track. */}
      <span className="flex w-max motion-safe:animate-tape">
        <span className="flex gap-7 pr-7">{items(0)}</span>
        <span className="flex gap-7 pr-7">{items(1)}</span>
      </span>
    </a>
  );
}

/** A rosette with two ribbons, in the tag's text colour; the ring is cut in the tag's cream. */
function AwardRosette() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="size-[1.25em] shrink-0" fill="currentColor">
      <polygon points="8.2,13.4 4.6,21.6 7.4,21 8.7,23.4 11.8,16.4" />
      <polygon points="15.8,13.4 19.4,21.6 16.6,21 15.3,23.4 12.2,16.4" />
      <polygon points="12.00,1.90 13.27,3.12 14.91,2.48 15.61,4.10 17.37,4.13 17.40,5.89 19.02,6.59 18.38,8.23 19.60,9.50 18.38,10.77 19.02,12.41 17.40,13.11 17.37,14.87 15.61,14.90 14.91,16.52 13.27,15.88 12.00,17.10 10.73,15.88 9.09,16.52 8.39,14.90 6.63,14.87 6.60,13.11 4.98,12.41 5.62,10.77 4.40,9.50 5.62,8.23 4.98,6.59 6.60,5.89 6.63,4.13 8.39,4.10 9.09,2.48 10.73,3.12" />
      <circle cx="12" cy="9.5" r="4.7" fill="none" stroke="var(--award-cream)" strokeWidth="1.3" />
    </svg>
  );
}
