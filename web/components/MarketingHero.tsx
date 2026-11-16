// The marketing page's hero, from the claude.ai design handoff "hero-3b": a dark band with a
// rotated magenta award tape, the nav, an "Award-winning" eyebrow, the headline with "missing."
// in teal, and pill CTAs. Colours are the hero-* and award-* tokens in globals.css; copy and
// link targets come from lib/marketing.ts.
import Image from "next/image";
import Link from "next/link";
import { Fragment } from "react";

import { AWARD_RESULTS_URL, HERO_LINKS, MARKETING_COPY, awardHref } from "@/lib/marketing";

const { hero } = MARKETING_COPY;
/** The handoff's 72px side padding on desktop; 16px gutters on a phone. */
const GUTTERS = "px-4 sm:px-8 lg:px-[72px]";
const PILL =
  "inline-flex items-center justify-center gap-2.5 rounded-full border-2 px-7 py-[17px] text-lg outline-none focus-visible:ring-3 focus-visible:ring-hero-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-hero";

export function MarketingHero() {
  const award = awardHref(AWARD_RESULTS_URL);
  return (
    <section
      aria-labelledby="hero-heading"
      className="relative flex min-h-svh flex-col overflow-hidden bg-hero text-hero-fg"
    >
      <AwardTape href={award} />

      <nav aria-label="Site" className={`${GUTTERS} flex items-center justify-between pt-7`}>
        <span className="flex items-center gap-3">
          <Image src="/brand/icon.svg" alt="" width={30} height={30} />
          <span className="text-lg font-semibold">TrialMatch Rx</span>
        </span>
        <Link
          href={HERO_LINKS.signIn}
          className="rounded text-[0.9375rem] font-medium text-hero-nav outline-none hover:text-hero-fg focus-visible:ring-2 focus-visible:ring-hero-accent"
        >
          {hero.signIn}
        </Link>
      </nav>

      <div
        className={`${GUTTERS} flex flex-1 flex-col justify-center gap-7 pt-14 pb-16 sm:pt-16 lg:pb-20`}
      >
        <a
          href={award}
          className="flex flex-wrap items-center gap-x-3.5 gap-y-3 self-start rounded font-mono text-[0.8125rem] font-bold tracking-[0.1em] text-award-cream uppercase outline-none hover:text-hero-fg focus-visible:ring-2 focus-visible:ring-hero-accent sm:text-[0.9375rem]"
        >
          <span className="rounded-md border-2 border-hero-ink bg-award-cream px-3 py-1.5 text-award-plum shadow-[3px_3px_0_var(--award-magenta)]">
            {hero.eyebrowTag}
          </span>
          {hero.eyebrowText}
        </a>
        <h1
          id="hero-heading"
          className="max-w-[1000px] text-[clamp(3rem,1.6rem+5.6vw,6rem)] leading-[0.98] font-bold tracking-[-0.045em] text-balance"
        >
          {hero.headlineLead}
          <span className="text-hero-accent">{hero.headlineAccent}</span>
        </h1>
        <p className="max-w-[640px] text-lg leading-[1.55] text-pretty text-hero-muted sm:text-xl">
          {MARKETING_COPY.subhead}
        </p>
        <div className="mt-1.5 flex flex-col gap-4 min-[480px]:flex-row min-[480px]:items-center min-[480px]:gap-5">
          <a
            href={HERO_LINKS.requestAccess}
            className={`${PILL} border-hero-ink bg-hero-accent font-bold text-hero-on-accent shadow-[5px_5px_0_var(--award-cream)] transition-[translate,box-shadow] duration-100 hover:translate-x-0.5 hover:translate-y-0.5 hover:shadow-[3px_3px_0_var(--award-cream)]`}
          >
            {hero.requestAccess} <span aria-hidden>→</span>
          </a>
          <Link
            href={HERO_LINKS.signIn}
            className={`${PILL} border-hero-outline font-semibold text-hero-fg hover:border-hero-nav`}
          >
            {hero.signIn}
          </Link>
        </div>
      </div>
    </section>
  );
}

/** The full-bleed magenta strip across the top, rotated, with a slow marquee (still under
 *  prefers-reduced-motion). It repeats the eyebrow's award, so it's hidden from screen readers
 *  and out of the tab order; it still links to the award for a pointer. */
function AwardTape({ href }: { href: string }) {
  const items = (copy: number) =>
    // Four rounds per copy, so one copy is wider than any screen and the loop never shows a gap.
    [0, 1, 2, 3].flatMap((round) =>
      hero.tape.map((item, i) => (
        <Fragment key={`${copy}-${round}-${i}`}>
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
      className="-mx-5 mt-[18px] block -rotate-[1.5deg] overflow-hidden border-y-[3px] border-hero-ink bg-award-magenta py-3 text-[1.125rem] font-extrabold tracking-[0.02em] whitespace-nowrap text-hero-ink uppercase italic"
    >
      {/* pr-7 matches the gap, so the second copy starts exactly half way along the track. */}
      <span className="flex w-max motion-safe:animate-tape">
        <span className="flex gap-7 pr-7">{items(0)}</span>
        <span className="flex gap-7 pr-7">{items(1)}</span>
      </span>
    </a>
  );
}
