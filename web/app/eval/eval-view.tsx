"use client";

// GET /api/eval/latest: matcher vs BM25 scores, the matcher's compile rate, the fixed sample's
// size, every `make eval` run newest first, and the same history per prompt version.
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type EvalLatest } from "@/lib/api";
import { byPromptVersion, EVAL_METRICS as METRICS, formatRate, lifts } from "@/lib/eval";
import { useLoad } from "@/lib/use-load";

const SYSTEMS = { matcher: "Matcher", bm25: "BM25 baseline" } as const;

function fmt(value: number | undefined): string {
  return value === undefined ? "–" : value.toFixed(3);
}

function signed(delta: number): string {
  return `${delta >= 0 ? "+" : "−"}${Math.abs(delta).toFixed(3)}`;
}

function ScoreCard({ title, metrics, empty, children }: {
  title: string;
  metrics: Record<string, number>;
  empty: string;
  children?: ReactNode;
}) {
  const ran = Object.keys(metrics).length > 0;
  return (
    <Card data-testid="eval-score">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {ran ? (
          <dl className="grid grid-cols-3 gap-4">
            {METRICS.map(({ key, label }) => (
              <div key={key}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-3xl font-semibold tabular-nums">{fmt(metrics[key])}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">{empty}</p>
        )}
        {children}
      </CardContent>
    </Card>
  );
}

function ByPromptVersion({ history }: { history: EvalLatest["history"] }) {
  const rows = byPromptVersion(history);
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>By prompt version</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <p className="mb-2 text-xs text-muted-foreground">
          The newest run of each system per prompt version, newest version first.
        </p>
        <table className="w-full text-sm" data-testid="eval-by-prompt">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="py-1 pr-4 font-normal">Prompts</th>
              {METRICS.map(({ key, label }) => (
                <th key={key} className="py-1 pr-4 text-right font-normal">
                  {label} matcher / BM25
                </th>
              ))}
              <th className="py-1 text-right font-normal">Compile rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.prompt_version ?? "none"} className="border-t">
                <td className="py-1 pr-4 font-mono text-xs">{row.prompt_version ?? "–"}</td>
                {METRICS.map(({ key }) => (
                  <td key={key} className="py-1 pr-4 text-right whitespace-nowrap tabular-nums">
                    {fmt(row.matcher?.metrics[key])} / {fmt(row.bm25?.metrics[key])}
                  </td>
                ))}
                <td className="py-1 text-right tabular-nums">
                  {formatRate(row.matcher?.metrics.compile_rate)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function History({ history }: { history: EvalLatest["history"] }) {
  if (history.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>History</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="eval-history">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="py-1 pr-4 font-normal">When</th>
              <th className="py-1 pr-4 font-normal">System</th>
              {METRICS.map(({ key, label }) => (
                <th key={key} className="py-1 pr-4 text-right font-normal">
                  {label}
                </th>
              ))}
              <th className="py-1 pr-4 text-right font-normal">Compile rate</th>
              <th className="py-1 pr-4 text-right font-normal">Pairs</th>
              <th className="py-1 pr-4 font-normal">Git</th>
              <th className="py-1 font-normal">Prompts</th>
            </tr>
          </thead>
          <tbody>
            {history.map((run) => (
              <tr key={run.id} className="border-t">
                <td className="py-1 pr-4 whitespace-nowrap tabular-nums">
                  {new Date(run.created_at).toLocaleString()}
                </td>
                <td className="py-1 pr-4">
                  <Badge variant={run.system === "matcher" ? "default" : "secondary"}>
                    {SYSTEMS[run.system]}
                  </Badge>
                </td>
                {METRICS.map(({ key }) => (
                  <td key={key} className="py-1 pr-4 text-right tabular-nums">
                    {fmt(run.metrics[key])}
                  </td>
                ))}
                <td className="py-1 pr-4 text-right tabular-nums">
                  {formatRate(run.metrics.compile_rate)}
                </td>
                <td className="py-1 pr-4 text-right tabular-nums">{run.sample_size}</td>
                <td className="py-1 pr-4 font-mono text-xs">{run.git_sha ?? "–"}</td>
                <td className="py-1 font-mono text-xs">{run.prompt_version ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

export function EvalView() {
  const { data, error } = useLoad(api.getEvalLatest);
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading eval…</p>;
  if (data.history.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No eval runs yet. Run <code className="font-mono">make eval</code> to score the matcher
        and the BM25 baseline.
      </p>
    );
  }
  const gains = lifts(data.metrics, data.baseline);
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm" data-testid="eval-sample">
        Sample: <span className="font-semibold tabular-nums">{data.sample_size}</span> judged
        (topic, trial) pairs over <span className="tabular-nums">{data.topics}</span> topics;{" "}
        <span className="tabular-nums">{data.dropped}</span> sampled{" "}
        {data.dropped === 1 ? "trial" : "trials"} dropped (gone from ClinicalTrials.gov, merged
        into another record, or no eligibility text).
      </p>
      {gains.length > 0 && (
        <p className="text-sm" data-testid="eval-lift">
          Matcher vs keyword search:{" "}
          {gains.map(({ key, label, delta }, i) => (
            <span key={key}>
              {i > 0 && ", "}
              <span className="font-semibold tabular-nums">{signed(delta)}</span> {label}
            </span>
          ))}
          .
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <ScoreCard
          title={SYSTEMS.matcher}
          metrics={data.metrics}
          empty="Not scored yet: make eval scores the matcher when ANTHROPIC_API_KEY is set."
        >
          <p className="mt-4 text-sm" data-testid="eval-compile-rate">
            Compile rate:{" "}
            <span className="font-semibold tabular-nums">{formatRate(data.compile_rate)}</span>
            <span className="text-muted-foreground">
              {" "}
              of the sample&apos;s criteria compiled to a rule (target ~60%)
            </span>
          </p>
        </ScoreCard>
        <ScoreCard title={SYSTEMS.bm25} metrics={data.baseline} empty="Run make eval.">
          <p className="mt-4 text-xs text-muted-foreground">
            Keyword search can&apos;t exclude anyone, so for accuracy it calls every judged trial
            eligible.
          </p>
        </ScoreCard>
      </div>
      <ByPromptVersion history={data.history} />
      <History history={data.history} />
    </div>
  );
}
