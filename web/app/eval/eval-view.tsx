"use client";

// GET /api/eval/latest: matcher vs BM25 scores, the fixed sample's size, and every
// `make eval` run newest first.
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type EvalLatest } from "@/lib/api";
import { useLoad } from "@/lib/use-load";

const METRICS = [
  { key: "ndcg@10", label: "nDCG@10" },
  { key: "p@10", label: "P@10" },
] as const;

const SYSTEMS = { matcher: "Matcher", bm25: "BM25 baseline" } as const;

function fmt(value: number | undefined): string {
  return value === undefined ? "–" : value.toFixed(3);
}

function ScoreCard({ title, metrics, empty }: {
  title: string;
  metrics: Record<string, number>;
  empty: string;
}) {
  const ran = Object.keys(metrics).length > 0;
  return (
    <Card data-testid="eval-score">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {ran ? (
          <dl className="grid grid-cols-2 gap-4">
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
        No eval runs yet. Run <code className="font-mono">make eval</code> to score the BM25
        baseline.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm" data-testid="eval-sample">
        Sample: <span className="font-semibold tabular-nums">{data.sample_size}</span> judged
        (topic, trial) pairs over <span className="tabular-nums">{data.topics}</span> topics;{" "}
        <span className="tabular-nums">{data.dropped}</span> sampled{" "}
        {data.dropped === 1 ? "trial" : "trials"} dropped (gone from ClinicalTrials.gov, merged
        into another record, or no eligibility text).
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <ScoreCard
          title={SYSTEMS.matcher}
          metrics={data.metrics}
          empty="Not scored yet: the matcher eval lands next (#11)."
        />
        <ScoreCard title={SYSTEMS.bm25} metrics={data.baseline} empty="Run make eval." />
      </div>
      <History history={data.history} />
    </div>
  );
}
