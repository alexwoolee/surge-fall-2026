import Link from "next/link";
import { ArrowClockwise, ArrowUpRight, Check, Minus } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import type { AnalysisState, WorkerId } from "@/lib/types";
import { DownloadBriefingButton } from "./download-briefing-button";
import { AnalystReviewBanner } from "./analyst-review-banner";
import { Outcome } from "./outcome";

export function PartialResultCard({ analysis, onRetry, retrying }: { analysis: AnalysisState; onRetry: (worker: WorkerId) => void; retrying: boolean }) {
  const briefing = analysis.briefing;
  const kept = Object.values(analysis.workers).filter((worker) => worker.returned && worker.validated);
  const missing = Object.values(analysis.workers).filter((worker) => !worker.returned || !worker.validated);
  const retryable = analysis.retryableWorkers ?? (analysis.isDemo ? ["flood" as const] : []);
  const notAssessable = analysis.reviewConditions.filter((condition) => condition.status === "not-assessable");
  return <Outcome tone="warning" labelledBy="partial-heading" title="Partial result"
    description={`${kept.map((worker) => worker.name).join(" and ") || "No"} evidence passed validation. Gaps stay visible and contribute no measurements.`}
    meta={`${kept.length} of ${Object.keys(analysis.workers).length} validated`}
    footer={<>
      {briefing && <DownloadBriefingButton briefing={briefing} sessionId={analysis.id} />}
      {retryable.map((worker) => <Button key={worker} variant="outline" onClick={() => onRetry(worker)} disabled={retrying}><ArrowClockwise size={14} aria-hidden="true"/>{retrying ? <span className="shimmer">Requesting retry…</span> : `Retry ${analysis.workers[worker].name}`}</Button>)}
      {briefing && <Link className="text-action" href={`/session/${analysis.id}/briefing`}>Open partial briefing <ArrowUpRight size={13} aria-hidden="true"/></Link>}
    </>}>
    <div className="evidence-columns">
      <section className="evidence-col" aria-labelledby="kept-heading">
        <h3 id="kept-heading">Validated</h3>
        <dl className="kv-list">{briefing?.metrics.map((metric) => <div key={metric.label}><dt><Check size={13} weight="bold" className="kv-ok" aria-hidden="true"/>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl>
      </section>
      <section className="evidence-col" aria-labelledby="missing-heading">
        <h3 id="missing-heading">{missing.length ? "Missing" : "Coverage limits"}</h3>
        {!missing.length && <p className="evidence-empty">{analysis.actualCoverage}</p>}
        <ul className="kv-list">{missing.map((worker) => <li key={worker.id}><Minus size={13} weight="bold" className="kv-missing" aria-hidden="true"/><div><strong>{worker.name}</strong><span>{worker.summary}</span></div></li>)}</ul>
      </section>
    </div>
    <AnalystReviewBanner conditions={analysis.reviewConditions}/>
    {notAssessable.length > 0 && <p className="outcome-footnote"><code className="rule-id">{notAssessable.map((condition) => condition.id).join(", ")}</code> not assessable. These conditions need missing evidence and were not treated as passing.</p>}
  </Outcome>;
}
