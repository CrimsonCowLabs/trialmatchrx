"use client";

// The home page's four cards: match a demo patient, open a trial's feasibility view, the
// latest match runs (GET /api/runs) and the latest eval (GET /api/eval/latest). Every figure
// shown comes from an API response.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { DemoPatientCards } from "@/components/DemoPatientCards";
import { OpenFeasibility } from "@/components/OpenFeasibility";
import { StatusPill } from "@/components/StatusPill";
import { TierChips } from "@/components/TierChips";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, errorMessage, type EvalLatest, type RunListItem } from "@/lib/api";
import { runLinks } from "@/lib/browse";
import { DEMO_PATIENTS, demoMatchRequest, type DemoPatient } from "@/lib/demo";
import { formatScore } from "@/lib/eval";
import { markGuideStep } from "@/lib/guide";
import { defaultFeasibilityNct, evalBars } from "@/lib/home";
import { useLoad } from "@/lib/use-load";

const RECENT_RUNS = 5;

const LINK = "link font-medium hover:underline";

const loadTrials = () => api.listTrials();
const loadRuns = () => api.listRuns({ kind: "match", limit: RECENT_RUNS });
const loadEval = () => api.getEvalLatest();

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function Failed({ error }: { error: string }) {
  return <p className="text-sm break-words text-destructive">{error}</p>;
}

export function MatchCard() {
  const router = useRouter();
  const [patient, setPatient] = useState<DemoPatient>(DEMO_PATIENTS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function findTrials() {
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await api.startMatch(demoMatchRequest(patient));
      // The guide's step 1 is checked when the ALS run starts.
      if (patient.id === "als") markGuideStep("als");
      router.push(`/match/${encodeURIComponent(run_id)}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Card data-testid="home-match" className="md:col-span-2">
      <CardHeader>
        <CardTitle>Match a patient</CardTitle>
        <CardDescription>
          Pick a synthetic patient, then rank recruiting trials with a quoted verdict on every
          criterion.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <DemoPatientCards
          selectedId={patient.id}
          onSelect={setPatient}
          className="lg:grid-cols-4"
        />
        <figure className="rounded-lg border border-line bg-surface-sunken p-3">
          <figcaption className="mb-1 text-xs font-medium tracking-wide text-ink-4 uppercase">
            {patient.name} · synthetic note
          </figcaption>
          <blockquote className="text-sm text-ink-2" data-testid="demo-note">
            {patient.note}
          </blockquote>
        </figure>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button onClick={findTrials} disabled={busy}>
            {busy ? "Starting…" : `Find trials for ${patient.name}`}
          </Button>
          <Link href="/match" className={`text-sm ${LINK}`}>
            Use another patient
          </Link>
        </div>
        {error && <Failed error={error} />}
      </CardContent>
    </Card>
  );
}

export function FeasibilityCard() {
  const { data, error } = useLoad(loadTrials);
  const defaultNct = data ? defaultFeasibilityNct(data) : null;
  return (
    <Card data-testid="home-feasibility">
      <CardHeader>
        <CardTitle>Trial feasibility</CardTitle>
        <CardDescription>
          See how many synthetic patients qualify for one trial, criterion by criterion.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {/* Remounts once the trials load, so the field picks up the default. */}
        <OpenFeasibility key={defaultNct ?? "none"} defaultNct={defaultNct} />
        {error ? (
          <Failed error={error} />
        ) : (
          data &&
          !defaultNct && (
            <Muted>
              No compiled trial yet. Run <code className="font-mono">make seed</code>, then
              compile one from{" "}
              <Link href="/trials" className={LINK}>
                Trials
              </Link>
              .
            </Muted>
          )
        )}
        <Link href="/trials" className={`self-start text-sm ${LINK}`}>
          Browse trials
        </Link>
      </CardContent>
    </Card>
  );
}

function RunRow({ run }: { run: RunListItem }) {
  return (
    <li className="border-t border-line-soft first:border-t-0">
      <Link
        href={runLinks(run).view}
        className="-mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-2.5 hover:bg-teal-selected"
      >
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-medium">{run.patient_label ?? "Patient not parsed"}</span>
          <span className="font-mono text-xs text-ink-4 tabular-nums">
            {new Date(run.created_at).toLocaleString(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </span>
        </span>
        {/* Counts mean nothing until the run is done; the status pill says why. */}
        {run.status === "done" ? (
          <TierChips counts={run.tier_counts} />
        ) : (
          <StatusPill status={run.status} />
        )}
      </Link>
    </li>
  );
}

export function RecentRunsCard() {
  const { data, error } = useLoad(loadRuns);
  return (
    <Card data-testid="home-runs">
      <CardHeader>
        <CardTitle>Recent runs</CardTitle>
        <CardDescription>Likely / needs info / ineligible trials per finished run.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error ? (
          <Failed error={error} />
        ) : !data ? (
          <Muted>Loading runs…</Muted>
        ) : data.length === 0 ? (
          <Muted>No match runs yet. Find trials for the demo patient to start one.</Muted>
        ) : (
          <ul className="flex flex-col text-sm">
            {data.map((run) => (
              <RunRow key={run.run_id} run={run} />
            ))}
          </ul>
        )}
        <Link href="/runs" className={`self-start text-sm ${LINK}`}>
          All runs
        </Link>
      </CardContent>
    </Card>
  );
}

// Literal class names so Tailwind sees them.
const BAR_SYSTEMS = {
  matcher: { label: "Matcher", fill: "bg-teal" },
  bm25: { label: "BM25", fill: "bg-ink-5" },
} as const;

function Bar({ system, value }: { system: keyof typeof BAR_SYSTEMS; value: number | null }) {
  const { label, fill } = BAR_SYSTEMS[system];
  const width = value === null ? 0 : Math.min(Math.max(value, 0), 1) * 100;
  return (
    <div className="grid grid-cols-[4.5rem_minmax(0,1fr)_3.25rem] items-center gap-2 text-xs">
      <span className="text-ink-3">{label}</span>
      <span className="h-2 overflow-hidden rounded-full bg-line-soft" aria-hidden>
        <span className={`block h-full rounded-full ${fill}`} style={{ width: `${width}%` }} />
      </span>
      <span className="text-right font-mono tabular-nums">{formatScore(value)}</span>
    </div>
  );
}

function EvalBars({ latest }: { latest: EvalLatest }) {
  const bars = evalBars(latest);
  if (bars.length === 0) {
    return (
      <Muted>
        No eval yet. Run <code className="font-mono">make eval</code> to score the matcher and a
        BM25 baseline against TREC expert labels.
      </Muted>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <dl className="flex flex-col gap-3">
        {bars.map(({ key, label, matcher, bm25 }) => (
          <div key={key} className="flex flex-col gap-1">
            <dt className="text-sm font-medium">{label}</dt>
            <dd className="flex flex-col gap-1">
              <Bar system="matcher" value={matcher} />
              <Bar system="bm25" value={bm25} />
            </dd>
          </div>
        ))}
      </dl>
      {latest.sample_size > 0 && (
        <Muted>
          {latest.sample_size} judged (topic, trial) pairs across {latest.topics} TREC topics.
        </Muted>
      )}
    </div>
  );
}

export function LatestEvalCard() {
  const { data, error } = useLoad(loadEval);
  return (
    <Card data-testid="home-eval">
      <CardHeader>
        <CardTitle>Latest eval</CardTitle>
        <CardDescription>The matcher against a BM25 baseline on TREC expert labels.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error ? (
          <Failed error={error} />
        ) : !data ? (
          <Muted>Loading eval…</Muted>
        ) : (
          <EvalBars latest={data} />
        )}
        <Link href="/eval" className={`self-start text-sm ${LINK}`}>
          Details
        </Link>
      </CardContent>
    </Card>
  );
}
