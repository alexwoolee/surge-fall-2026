import Link from "next/link";
import { RefreshCw, ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AnalysisState, WorkerId } from "@/lib/types";
import { StatusOrb } from "./agent-status";
import { DownloadBriefingButton } from "./download-briefing-button";
import { AnalystReviewBanner } from "./analyst-review-banner";

export function PartialResultCard({ analysis, onRetry, retrying }: { analysis: AnalysisState; onRetry: (worker: WorkerId) => void; retrying: boolean }) {
  const briefing = analysis.briefing;
  const kept = Object.values(analysis.workers).filter((worker) => worker.returned && worker.validated);
  const missing = Object.values(analysis.workers).filter((worker) => !worker.returned || !worker.validated);
  const retryable = analysis.retryableWorkers ?? (analysis.isDemo ? ["flood" as const] : []);
  const notAssessable = analysis.reviewConditions.filter((condition) => condition.status === "not-assessable");
  return <section className="result-card result-card--amber" aria-labelledby="partial-heading">
    <header className="result-header"><span className="outcome-badge badge-amber">Partial result</span><span>{kept.length} of {Object.keys(analysis.workers).length} investigations validated</span></header>
    <div className="result-body"><h2 id="partial-heading">Available evidence is retained. The gaps remain visible.</h2>
      <p>{kept.map((worker) => worker.name).join(" and ")} evidence passed validation. {missing.length ? `${missing.map((worker) => worker.name).join(" and ")} evidence is unavailable or did not pass validation and contributes no measurements.` : "The supplied observations do not provide complete coverage of the requested area or time window."}</p>
      <div className="evidence-grid"><section className="evidence-panel"><h3><StatusOrb status="complete"/>Kept — validated evidence</h3><dl className="evidence-list">{briefing?.metrics.map((metric) => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl></section>
        <section className="evidence-panel"><h3><StatusOrb status="unknown"/>{missing.length ? "Missing evidence" : "Coverage limits"}</h3>{!missing.length && <p>{analysis.actualCoverage}</p>}<ul className="missing-evidence">{missing.map((worker) => <li key={worker.id}>{worker.name}<span>{worker.summary}</span></li>)}</ul></section></div>
      <AnalystReviewBanner conditions={analysis.reviewConditions}/>
      {notAssessable.length > 0 && <p className="unassessed-note"><strong>{notAssessable.map((condition) => condition.id).join(", ")} — Not assessable.</strong> These conditions need missing evidence and have not been treated as passing.</p>}
      <div className="result-actions">{briefing && <DownloadBriefingButton briefing={briefing} sessionId={analysis.id}/>}
        {retryable.map((worker) => <Button key={worker} variant="outline" onClick={() => onRetry(worker)} disabled={retrying}><RefreshCw size={15} aria-hidden="true"/>{retrying ? "Requesting retry…" : `Retry ${analysis.workers[worker].name}`}</Button>)}
        {briefing && <Link className="text-action" href={`/session/${analysis.id}/briefing`}>Open partial briefing <ArrowUpRight size={14} aria-hidden="true"/></Link>}
      </div>
    </div>
  </section>;
}
