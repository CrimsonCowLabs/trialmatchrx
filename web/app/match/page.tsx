"use client";

import { ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Page } from "@/components/AppShell";
import { DemoPatientCards } from "@/components/DemoPatientCards";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { DEMO_PATIENTS, demoPatientForNote, type DemoPatient } from "@/lib/demo";
import {
  AGENT_STEPS,
  DEFAULT_RADIUS_MI,
  RADII_MI,
  runStatsHint,
  type RadiusMi,
} from "@/lib/match-form";
import { useLoad } from "@/lib/use-load";

const loadStats = () => api.getRunStats();

export default function MatchPage() {
  const router = useRouter();
  const [note, setNote] = useState(DEMO_PATIENTS[0].note);
  const [condition, setCondition] = useState(DEMO_PATIENTS[0].searchCondition);
  const [radius, setRadius] = useState<RadiusMi>(DEFAULT_RADIUS_MI);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The card stays highlighted only while the note is exactly that patient's.
  const loaded = demoPatientForNote(note);

  function pick(p: DemoPatient) {
    setNote(p.note);
    setCondition(p.searchCondition);
  }
  // A failed stats call only hides the hint; it must not block matching.
  const hint = runStatsHint(useLoad(loadStats).data);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await api.startMatch({ note, condition, radius_mi: radius });
      router.push(`/match/${run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <Page width="wide">
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }]}
        title="Match a patient"
        description="Pick a demo patient or paste a note; the agent finds recruiting trials nearby and checks every criterion."
      />
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Card>
          <CardContent>
            <form onSubmit={onSubmit} className="flex flex-col gap-5">
              <div className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Demo patients · synthetic</span>
                <DemoPatientCards selectedId={loaded?.id ?? null} onSelect={pick} />
              </div>
              <div className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <label htmlFor="note" className="text-sm font-medium">
                    Patient note
                  </label>
                  {loaded ? (
                    <span className="text-xs text-ink-3" data-testid="demo-loaded">
                      {loaded.name} loaded ·{" "}
                      <button
                        type="button"
                        onClick={() => setNote("")}
                        className="link font-medium hover:underline"
                      >
                        Clear
                      </button>
                    </span>
                  ) : (
                    note && (
                      <span className="text-xs text-ink-4" data-testid="demo-edited">
                        Edited note
                      </span>
                    )
                  )}
                </div>
                <Textarea
                  id="note"
                  name="note"
                  rows={6}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  className="min-h-32"
                  placeholder="Age, sex, diagnoses, labs, medications, location…"
                  required
                />
                <p className="flex items-start gap-1.5 text-xs text-ink-3">
                  <ShieldAlert aria-hidden className="mt-px size-3.5 shrink-0 text-verdict-unknown" />
                  Synthetic data only. Never paste real patient data.
                </p>
              </div>

              <div className="flex flex-col gap-5 sm:flex-row sm:items-end">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <label htmlFor="condition" className="text-sm font-medium">
                    Condition
                  </label>
                  <Input
                    id="condition"
                    name="condition"
                    value={condition}
                    onChange={(e) => setCondition(e.target.value)}
                    required
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <span id="radius-label" className="text-sm font-medium">
                    Radius
                  </span>
                  <div
                    role="radiogroup"
                    aria-labelledby="radius-label"
                    className="inline-flex w-fit rounded-lg border border-input p-0.5"
                  >
                    {RADII_MI.map((r) => (
                      <label
                        key={r}
                        className="cursor-pointer rounded-md px-3 py-1 text-sm whitespace-nowrap text-ink-3 has-checked:bg-teal-selected has-checked:font-medium has-checked:text-teal-strong has-focus-visible:ring-3 has-focus-visible:ring-ring/50"
                      >
                        <input
                          type="radio"
                          name="radius_mi"
                          value={r}
                          checked={radius === r}
                          onChange={() => setRadius(r)}
                          className="sr-only"
                        />
                        {r} mi
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
                <Button
                  type="submit"
                  size="lg"
                  className="px-4"
                  disabled={busy || !note.trim() || !condition.trim()}
                >
                  {busy ? "Starting…" : "Find trials"}
                </Button>
                {hint && (
                  <p className="text-xs text-ink-4" data-testid="run-stats-hint">
                    {hint}
                  </p>
                )}
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>What the agent does</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="flex flex-col gap-3">
              {AGENT_STEPS.map((step, i) => (
                <li key={step.title} className="flex gap-3">
                  <span
                    aria-hidden
                    className="flex size-6 shrink-0 items-center justify-center rounded-full bg-teal-tint font-mono text-xs font-medium text-teal-strong"
                  >
                    {i + 1}
                  </span>
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="font-medium">{step.title}</span>
                    <span className="text-ink-3">{step.detail}</span>
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>
    </Page>
  );
}
