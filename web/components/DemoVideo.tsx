"use client";
// The marketing page's click-to-load demo video (SPEC.md "Marketing and accounts", section 2): a
// poster with a play button, and youtube-nocookie.com only after the click, so a visit sends
// nothing to YouTube. While DEMO_VIDEO_ID is unset the poster reads "Demo video coming soon".
import { Play } from "lucide-react";
import Image from "next/image";
import { useState } from "react";

import type { DemoVideo as DemoVideoState } from "@/lib/marketing";

/** `poster` is a still behind the play button: a real screenshot of the app, dimmed. */
export function DemoVideo({ video, poster }: { video: DemoVideoState; poster: string }) {
  const [playing, setPlaying] = useState(false);
  const ready = video.kind === "ready";
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-card bg-replay text-replay-fg ring-1 ring-replay-line">
      {ready && playing ? (
        <iframe
          src={video.embedUrl}
          title="TrialMatch Rx demo video"
          allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
          allowFullScreen
          referrerPolicy="strict-origin-when-cross-origin"
          className="absolute inset-0 size-full"
        />
      ) : (
        <>
          <Image
            src={poster}
            alt=""
            fill
            sizes="(min-width: 1152px) 1088px, 100vw"
            className="object-cover object-top opacity-10 blur-[2px] grayscale"
          />
          <button
            type="button"
            disabled={!ready}
            onClick={() => setPlaying(true)}
            className="group absolute inset-0 flex flex-col items-center justify-center gap-4 outline-none focus-visible:ring-3 focus-visible:ring-replay-progress focus-visible:ring-inset disabled:cursor-default"
          >
            <span
              aria-hidden
              className={`flex size-16 items-center justify-center rounded-full sm:size-20 ${ready ? "bg-teal text-replay-fg transition-colors group-hover:bg-teal-strong" : "border border-replay-line text-replay-muted"}`}
            >
              <Play className="ml-1 size-7 sm:size-8" fill="currentColor" strokeWidth={0} />
            </span>
            <span className={`text-sm font-medium sm:text-base ${ready ? "" : "text-replay-muted"}`}>
              {video.label}
            </span>
          </button>
        </>
      )}
    </div>
  );
}
