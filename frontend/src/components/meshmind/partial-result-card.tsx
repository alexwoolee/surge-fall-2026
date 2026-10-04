import Link from "next/link";
import { ArrowClockwise, ArrowUpRight, Check, Minus } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import type { AnalysisState, WorkerId } from "@/lib/types";
import { presentBriefing } from "@/lib/briefing-presentation";
import { DownloadBriefingButton } from "./download-briefing-button";
import { AnalystReviewBanner } from "./analyst-review-banner";
import { BriefingCard } from "./briefing-card";
import { Outcome } from "./outcome";

export function PartialResultCard({ analysis, onRetry, retrying }: { analysis: AnalysisState; onRetry: (worker: WorkerId) => void; retrying: boolean }) {
  const briefing = analysis.briefing;
  const display = briefing ? presentBriefing(briefing) : null;
  const kept = Object.values(analysis.workers).filter((worker) => worker.returned && worker.validated);
  const missing = Object.values(analysis.workers).filter((worker) => !worker.returned || !worker.validated);
  const retryable = analysis.retryableWorkers ?? (analysis.isDemo ? ["flood" as const] : []);
  if (missing.length === 0) return <BriefingCard analysis={analysis} />;
  return <Outcome tone="warning" labelledBy="partial-heading" title="Worker needs attention"
    description={kept.length ? `${kept.map((worker) => worker.name).join(" and ")} evidence passed validation and is retained.` : "No worker evidence has passed validation yet."}
    meta={`${kept.length} of ${Object.keys(analysis.workers).length} validated`}
    footer={<>
      {briefing && <DownloadBriefingButton briefing={briefing} sessionId={analysis.id} />}
      {retryable.map((worker) => analysis.workers[worker] && <Button key={worker} variant="outline" onClick={() => onRetry(worker)} disabled={retrying}><ArrowClockwise size={14} aria-hidden="true"/>{retrying ? <span className="shimmer">Requesting retry…</span> : `Retry ${analysis.workers[worker]?.name}`}</Button>)}
      {briefing && <Link className="text-action" href={`/session/${analysis.id}/briefing`}>{briefing.risk ? "Open screening briefing" : "Open briefing"} <ArrowUpRight size={13} aria-hidden="true"/></Link>}
    </>}>
    <div className="evidence-columns">
      {(display?.metrics.length ?? 0) > 0 && <section className="evidence-col" aria-labelledby="kept-heading">
        <h3 id="kept-heading">Validated evidence</h3>
        <dl className="kv-list">{display?.metrics.map((metric) => <div key={metric.label}><dt><Check size={13} weight="bold" className="kv-ok" aria-hidden="true"/>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl>
      </section>}
      <section className="evidence-col" aria-labelledby="worker-attention-heading">
        <h3 id="worker-attention-heading">Worker status</h3>
        <ul className="kv-list">{missing.map((worker) => <li key={worker.id}><Minus size={13} weight="bold" className="kv-missing" aria-hidden="true"/><div><strong>{worker.name}</strong><span>{worker.summary}</span></div></li>)}</ul>
      </section>
    </div>
    <AnalystReviewBanner conditions={display?.conditions ?? analysis.reviewConditions.filter((condition) => condition.status !== "not-assessable")}/>
  </Outcome>;
}
