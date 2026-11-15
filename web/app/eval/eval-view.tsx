"use client";

// GET /api/eval/latest: matcher vs BM25 scores with the gain, the matcher's compile rate
// against the target from settings, the fixed sample's size, and every `make eval` run newest
// first (all runs, or grouped by prompt version). Every figure shown comes from that response.
import { useState, type ReactNode } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui/card";
import { api, type EvalLatest } from "@/lib/api";
import {
  EVAL_METRICS as METRICS,
  formatGain,
  formatRate,
  formatScore,
  formatTarget,
  groupByPromptVersion,
  metricCards,
  type MetricCard,
} from "@/lib/eval";
import { useLoad } from "@/lib/use-load";

type Run = EvalLatest["history"][number];

const TITLE = "Eval against TREC expert labels";

// Literal class names so Tailwind sees them.
const SYSTEMS = {
  matcher: { label: "Matcher", pill: "bg-teal-tint text-teal-strong", fill: "bg-teal" },
  bm25: { label: "BM25 baseline", pill: "bg-line-soft text-ink-2", fill: "bg-line-strong" },
} as const;

function Header({ latest }: { latest?: EvalLatest }) {
  const ran = latest && latest.history.length > 0;
  return (
    <PageHeader
      breadcrumb={[{ label: "Home", href: "/" }]}
      title={TITLE}
      description={
        ran && (
          <p data-testid="eval-sample">
            <span className="hidden sm:inline">
              <Num>{latest.sample_size}</Num> judged (topic, trial) pairs over{" "}
              <Num>{latest.topics}</Num> topics.
              {latest.dropped > 0 && (
                <>
                  {" "}
                  <Num>{latest.dropped}</Num> sampled {latest.dropped === 1 ? "trial" : "trials"}{" "}
                  dropped: gone from ClinicalTrials.gov, merged into another record, or no
                  eligibility text.
                </>
              )}
            </span>
            <span className="sm:hidden">
              {latest.sample_size} pairs · {latest.topics} topics · TREC labels
            </span>
          </p>
        )
      }
    />
  );
}

function Num({ children }: { children: number }) {
  return <span className="font-mono text-foreground tabular-nums">{children}</span>;
}

function Bar({ system, value }: { system: keyof typeof SYSTEMS; value: number | null }) {
  const width = value === null ? 0 : Math.min(Math.max(value, 0), 1) * 100;
  return (
    <span className="block h-1.5 overflow-hidden rounded-full bg-line-soft" aria-hidden>
      <span
        className={`block h-full rounded-full ${SYSTEMS[system].fill}`}
        style={{ width: `${width}%` }}
      />
    </span>
  );
}

function MetricScoreCard({ card }: { card: MetricCard }) {
  const { label, matcher, bm25, gain } = card;
  return (
    <Card className="gap-3 px-5 py-5" data-testid="eval-metric">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium text-ink-4">{label}</h2>
        {gain !== null && (
          <span
            className={`rounded-md px-2 py-0.5 font-mono text-xs font-semibold tabular-nums ${gain >= 0 ? "bg-verdict-pass-bg text-verdict-pass" : "bg-verdict-fail-bg text-verdict-fail"}`}
            title="Matcher minus BM25"
            data-testid="eval-gain"
          >
            {formatGain(gain)}
          </span>
        )}
      </div>
      <p className="flex flex-wrap items-baseline gap-x-2.5">
        <span className="font-mono text-3xl font-semibold tracking-tight tabular-nums sm:text-4xl">
          {formatScore(matcher)}
        </span>
        <span className="font-mono text-sm text-ink-5 tabular-nums">vs {formatScore(bm25)}</span>
        <span className="sr-only">
          Matcher {formatScore(matcher)}, BM25 baseline {formatScore(bm25)}
        </span>
      </p>
      <div className="flex flex-col gap-1">
        <Bar system="matcher" value={matcher} />
        <Bar system="bm25" value={bm25} />
      </div>
    </Card>
  );
}

function CompileRateCard({ rate, target }: { rate: number | null; target: number }) {
  return (
    <Card
      className="flex-row items-center justify-between gap-3 px-5 py-4 sm:flex-col sm:items-stretch sm:justify-start sm:gap-2 sm:py-5"
      data-testid="eval-compile-rate"
    >
      <div>
        <h2 className="text-sm font-medium text-ink-4">Compile rate</h2>
        <p className="mt-0.5 text-xs text-ink-4 sm:hidden">target ~{formatTarget(target)}</p>
      </div>
      <p className="font-mono text-2xl font-semibold tracking-tight tabular-nums sm:text-4xl">
        {formatRate(rate)}
      </p>
      <p className="hidden text-sm text-ink-4 sm:block">
        {rate === null ? "not scored yet" : "of criteria compiled to a rule"} · target ~
        {formatTarget(target)}
      </p>
    </Card>
  );
}

function Legend({ matcherScored }: { matcherScored: boolean }) {
  return (
    <div className="flex flex-col gap-1.5 text-sm text-ink-4 sm:flex-row sm:gap-4">
      <span className="flex items-center gap-1.5">
        <span aria-hidden className={`size-2.5 shrink-0 rounded-xs ${SYSTEMS.matcher.fill}`} />
        {matcherScored
          ? "Matcher"
          : "Matcher: not scored yet. make eval scores it when ANTHROPIC_API_KEY is set."}
      </span>
      <span className="flex items-start gap-1.5 sm:items-center">
        <span
          aria-hidden
          className={`mt-1.5 size-2.5 shrink-0 rounded-xs sm:mt-0 ${SYSTEMS.bm25.fill}`}
        />
        <span>
          BM25 baseline. Keyword search can&apos;t exclude anyone, so for accuracy it calls every
          judged trial eligible.
        </span>
      </span>
    </div>
  );
}

function SystemPill({ system }: { system: Run["system"] }) {
  const { label, pill } = SYSTEMS[system];
  return (
    <span className={`rounded-full px-2.5 py-0.5 font-sans text-xs font-medium whitespace-nowrap ${pill}`}>
      {label}
    </span>
  );
}

function when(run: Run): string {
  return new Date(run.created_at).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

const TH = "px-3 py-2.5 text-xs font-medium tracking-wide text-ink-4 uppercase";
const TD = "px-3 py-3";

function HistoryRow({ run }: { run: Run }) {
  return (
    <tr className="border-t border-line-soft font-mono tabular-nums">
      <td className={`${TD} pl-5 whitespace-nowrap`}>{when(run)}</td>
      <td className={TD}>
        <SystemPill system={run.system} />
      </td>
      {METRICS.map(({ key }) => (
        <td key={key} className={`${TD} text-right`}>
          {formatScore(run.metrics[key])}
        </td>
      ))}
      <td className={`${TD} text-right`}>{formatRate(run.metrics.compile_rate)}</td>
      <td className={`${TD} text-right text-ink-4`}>{run.sample_size}</td>
      <td className={`${TD} text-ink-4`}>{run.git_sha ?? "–"}</td>
      <td className={`${TD} pr-5 text-xs break-all text-ink-4`}>{run.prompt_version ?? "–"}</td>
    </tr>
  );
}

function GroupHeading({ version, count }: { version: string | null; count: number }) {
  return (
    <span className="flex flex-wrap items-baseline gap-x-2">
      <span className="font-mono text-xs break-all text-ink-2">{version ?? "No prompt version"}</span>
      <span className="text-xs text-ink-4">
        {count} {count === 1 ? "run" : "runs"}
      </span>
    </span>
  );
}

function HistoryTable({ history, grouped }: { history: Run[]; grouped: boolean }) {
  const head = (
    <thead className="text-left">
      <tr>
        <th className={`${TH} pl-5`}>When</th>
        <th className={TH}>System</th>
        {METRICS.map(({ key, label }) => (
          <th key={key} className={`${TH} text-right normal-case`}>
            {label}
          </th>
        ))}
        <th className={`${TH} text-right`}>Compile</th>
        <th className={`${TH} text-right`}>Pairs</th>
        <th className={TH}>Git</th>
        <th className={`${TH} pr-5`}>Prompts</th>
      </tr>
    </thead>
  );
  const columns = METRICS.length + 6;
  return (
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full text-sm" data-testid="eval-history">
        {head}
        {grouped ? (
          groupByPromptVersion(history).map(({ prompt_version, runs }) => (
            <tbody key={prompt_version ?? "none"} data-testid="eval-prompt-group">
              <tr className="border-t border-line bg-surface-sunken">
                <th colSpan={columns} scope="colgroup" className="px-5 py-2 text-left font-normal">
                  <GroupHeading version={prompt_version} count={runs.length} />
                </th>
              </tr>
              {runs.map((run) => (
                <HistoryRow key={run.id} run={run} />
              ))}
            </tbody>
          ))
        ) : (
          <tbody>
            {history.map((run) => (
              <HistoryRow key={run.id} run={run} />
            ))}
          </tbody>
        )}
      </table>
    </div>
  );
}

function HistoryCard({ run }: { run: Run }) {
  return (
    <li className="flex flex-col gap-2 border-t border-line-soft px-4 py-3 first:border-t-0">
      <div className="flex items-center justify-between gap-2">
        <SystemPill system={run.system} />
        <span className="font-mono text-xs text-ink-4 tabular-nums">{when(run)}</span>
      </div>
      <dl className="grid grid-cols-4 gap-2 font-mono text-sm tabular-nums">
        {METRICS.map(({ key, label }) => (
          <div key={key}>
            <dt className="font-sans text-xs text-ink-4">{label}</dt>
            <dd>{formatScore(run.metrics[key])}</dd>
          </div>
        ))}
        <div>
          <dt className="font-sans text-xs text-ink-4">Compile</dt>
          <dd>{formatRate(run.metrics.compile_rate)}</dd>
        </div>
      </dl>
      <p className="font-mono text-xs break-all text-ink-4">
        {run.sample_size} pairs · {run.git_sha ?? "–"} · {run.prompt_version ?? "–"}
      </p>
    </li>
  );
}

function HistoryCards({ history, grouped }: { history: Run[]; grouped: boolean }) {
  if (!grouped) {
    return (
      <ul className="md:hidden">
        {history.map((run) => (
          <HistoryCard key={run.id} run={run} />
        ))}
      </ul>
    );
  }
  return (
    <div className="md:hidden">
      {groupByPromptVersion(history).map(({ prompt_version, runs }) => (
        <section key={prompt_version ?? "none"} className="border-t border-line first:border-t-0">
          <h3 className="bg-surface-sunken px-4 py-2">
            <GroupHeading version={prompt_version} count={runs.length} />
          </h3>
          <ul>
            {runs.map((run) => (
              <HistoryCard key={run.id} run={run} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

const VIEWS = [
  { grouped: false, label: "All runs" },
  { grouped: true, label: "By prompt version" },
] as const;

function History({ history }: { history: Run[] }) {
  const [grouped, setGrouped] = useState(false);
  // Below md the history starts collapsed behind "View history (N runs)".
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls="eval-history-card"
        className="link self-start px-1 py-1.5 text-sm font-medium md:hidden"
        data-testid="eval-history-toggle"
      >
        {open ? "Hide history" : `View history (${history.length} ${history.length === 1 ? "run" : "runs"})`}
      </button>
      <Card
        id="eval-history-card"
        className={`gap-0 py-0 ${open ? "" : "max-md:hidden"}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line-soft px-4 py-3 sm:px-5">
          <h2 className="text-base font-semibold">History</h2>
          <div
            role="group"
            aria-label="History view"
            className="flex rounded-lg bg-surface-sunken p-0.5 text-sm font-medium"
          >
            {VIEWS.map((view) => (
              <button
                key={view.label}
                type="button"
                aria-pressed={grouped === view.grouped}
                onClick={() => setGrouped(view.grouped)}
                className={`rounded-md px-3 py-1 ${grouped === view.grouped ? "bg-surface text-foreground shadow-xs" : "text-ink-3"}`}
              >
                {view.label}
              </button>
            ))}
          </div>
        </div>
        <HistoryTable history={history} grouped={grouped} />
        <HistoryCards history={history} grouped={grouped} />
      </Card>
    </>
  );
}

function Results({ latest }: { latest: EvalLatest }) {
  const cards = metricCards(latest.metrics, latest.baseline);
  return (
    <>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 sm:gap-4 xl:grid-cols-[repeat(3,minmax(0,1fr))_16rem]">
        {cards.map((card) => (
          <MetricScoreCard key={card.key} card={card} />
        ))}
        <CompileRateCard rate={latest.compile_rate} target={latest.compile_rate_target} />
      </div>
      <Legend matcherScored={Object.keys(latest.metrics).length > 0} />
      <History history={latest.history} />
    </>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

export function EvalView() {
  const { data, error } = useLoad(api.getEvalLatest);
  return (
    <>
      <Header latest={data ?? undefined} />
      {error ? (
        <p className="text-sm break-words text-destructive">{error}</p>
      ) : !data ? (
        <Muted>Loading eval…</Muted>
      ) : data.history.length === 0 ? (
        <Card className="px-5 py-6" data-testid="eval-empty">
          <h2 className="text-base font-semibold">No eval runs yet</h2>
          <Muted>
            Run <code className="font-mono">make eval</code> to score the matcher and the BM25
            baseline on the fixed TREC sample. The compile rate is measured against a target of
            ~{formatTarget(data.compile_rate_target)}.
          </Muted>
        </Card>
      ) : (
        <Results latest={data} />
      )}
    </>
  );
}
