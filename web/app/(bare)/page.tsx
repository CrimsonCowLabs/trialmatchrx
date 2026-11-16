// The public marketing page (SPEC.md "Marketing and accounts"), for trial sponsors and CROs:
// hero (components/MarketingHero), demo video, the three moments, trust, award (hidden until set), request access, footer.
// Copy and config live in lib/marketing.ts; the screenshots are real captures of the app
// (synthetic patients, DEMO_MODE=replay) in public/moments.
import { Check, CircleHelp } from "lucide-react";
import type { Metadata } from "next";
import Image, { getImageProps } from "next/image";

import { DemoVideo } from "@/components/DemoVideo";
import { MarketingHero } from "@/components/MarketingHero";
import { RequestAccessForm } from "@/components/RequestAccessForm";
import { REQUEST_ACCESS_ID } from "@/lib/access-request";
import {
  AWARD_PHOTOS,
  AWARD_RESULTS_URL,
  AWARD_TITLE,
  DEMO_VIDEO_ID,
  MARKETING_COPY,
  MARKETING_METADATA,
  awardSection,
  demoVideo,
  type Moment,
  type MomentScreenshot,
} from "@/lib/marketing";

export const metadata: Metadata = MARKETING_METADATA;

/** The page's one column: 16px gutters on a phone, wider from `sm`. */
const COLUMN = "mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8";

export default function MarketingPage() {
  const award = awardSection(AWARD_RESULTS_URL, AWARD_PHOTOS);
  return (
    <div className="flex flex-1 flex-col">
      <MarketingHero />

      <section aria-label="Demo video" className={`${COLUMN} pb-20 sm:pb-28`}>
        <DemoVideo
          video={demoVideo(DEMO_VIDEO_ID)}
          poster={MARKETING_COPY.moments[0].screenshot.src}
        />
      </section>

      <div className="flex flex-col gap-20 pb-20 sm:gap-28 sm:pb-28">
        {MARKETING_COPY.moments.map((m, i) => (
          <MomentSection key={m.name} moment={m} flip={i % 2 === 1} />
        ))}
      </div>

      <Trust />

      {award && (
        <section aria-labelledby="award-heading" className={`${COLUMN} pb-20 sm:pb-28`}>
          <h2 id="award-heading" className="text-2xl font-semibold tracking-tight text-ink">
            {AWARD_TITLE}
          </h2>
          <a href={award.resultsUrl} className="link mt-2 inline-block text-sm font-medium">
            {MARKETING_COPY.awardResultsLink}
          </a>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {award.photos.map((p) => (
              <Image
                key={p.src}
                src={p.src}
                alt={p.alt}
                width={p.width}
                height={p.height}
                sizes="(min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"
                className="h-auto w-full rounded-card border border-line"
              />
            ))}
          </div>
        </section>
      )}

      <section
        id={REQUEST_ACCESS_ID}
        aria-labelledby="request-access-heading"
        className="scroll-mt-8 border-t border-line bg-surface"
      >
        <div className={`${COLUMN} grid gap-8 py-16 sm:py-24 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16`}>
          <div className="flex flex-col gap-3">
            <h2
              id="request-access-heading"
              className="text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl"
            >
              {MARKETING_COPY.requestAccess}
            </h2>
            <p className="max-w-md text-ink-3">{MARKETING_COPY.requestAccessNote}</p>
          </div>
          <RequestAccessForm />
        </div>
      </section>

      <footer className="border-t border-line bg-surface">
        <p className={`${COLUMN} py-6 text-sm text-ink-4`}>{MARKETING_COPY.footer}</p>
      </footer>
    </div>
  );
}

function MomentSection({ moment, flip }: { moment: Moment; flip: boolean }) {
  const id = `moment-${moment.name.toLowerCase()}`;
  return (
    <section
      aria-labelledby={id}
      className={`${COLUMN} grid items-center gap-6 sm:gap-8 lg:grid-cols-12 lg:gap-12`}
    >
      <div className={`flex flex-col gap-4 lg:col-span-4 ${flip ? "lg:order-last" : ""}`}>
        <p className="font-mono text-sm text-teal-strong">{moment.name}</p>
        <h2 id={id} className="text-3xl leading-tight font-semibold tracking-tight text-balance text-ink sm:text-4xl">
          {moment.heading}
        </h2>
        {moment.unknownsLine && (
          // Marked like an unknown verdict in the app: the Needs info tier lists what's missing.
          <h3 className="flex items-start gap-2.5 text-lg font-medium text-ink-2">
            <span
              aria-hidden
              className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-verdict-unknown-bg text-verdict-unknown"
            >
              <CircleHelp className="size-3.5" strokeWidth={2.5} />
            </span>
            {moment.unknownsLine}
          </h3>
        )}
      </div>
      <figure className="min-w-0 lg:col-span-8">
        <Screenshot shot={moment.screenshot} />
      </figure>
    </section>
  );
}

/** The desktop capture, or below `sm` the same view captured at 390px (a desktop capture shrunk
 *  to a phone is unreadable). */
function Screenshot({ shot }: { shot: MomentScreenshot }) {
  const { mobile: small, ...large } = shot;
  const desktopSizes = "(min-width: 1280px) 760px, (min-width: 1024px) 66vw, 100vw";
  const desktop = getImageProps({ ...large, sizes: desktopSizes }).props.srcSet;
  // The <img> is the 390px capture; the <source> swaps in the desktop one from `sm`.
  const { props: img } = getImageProps({ ...small, alt: shot.alt, sizes: "100vw" });
  return (
    <picture>
      {/* width/height on the source give the desktop aspect ratio before it loads. */}
      <source
        media="(min-width: 640px)"
        srcSet={desktop}
        sizes={desktopSizes}
        width={large.width}
        height={large.height}
      />
      <img
        {...img}
        alt={shot.alt}
        className="h-auto w-full rounded-card border border-line bg-surface shadow-[0_1px_2px_var(--line-strong),0_12px_32px_-12px_var(--line-strong)]"
      />
    </picture>
  );
}

function Trust() {
  return (
    <section aria-labelledby="trust-heading" className={`${COLUMN} pb-20 sm:pb-28`}>
      <h2 id="trust-heading" className="sr-only">
        Trust
      </h2>
      <ul className="grid overflow-hidden rounded-card border border-line bg-surface sm:grid-cols-2">
        {MARKETING_COPY.trust.map((line) => (
          <li
            key={line}
            className="flex items-start gap-3 border-b border-line-soft px-5 py-5 last:border-b-0 sm:px-6 sm:py-6 sm:nth-[odd]:border-r sm:nth-last-[-n+2]:border-b-0"
          >
            <span
              aria-hidden
              className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-verdict-pass-bg text-verdict-pass"
            >
              <Check className="size-3.5" strokeWidth={3} />
            </span>
            <span className="text-lg font-medium text-ink">{line}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
