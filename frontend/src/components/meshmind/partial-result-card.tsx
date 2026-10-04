import Link from "next/link";
import { RefreshCw, ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AnalysisState } from "@/lib/types";
import { StatusOrb } from "./agent-status";
import { DownloadBriefingButton } from "./download-briefing-button";
import { AnalystReviewBanner } from "./analyst-review-banner";

export function PartialResultCard({ analysis, onRetry, retrying }: { analysis: AnalysisState; onRetry: () => void; retrying: boolean }) {
  const briefing = analysis.briefing;
  const returnedCount = Object.values(analysis.workers).filter((worker) => worker.returned && worker.validated).length;
  const notAssessable = analysis.reviewConditions.filter((condition) => condition.status === "not-assessable");

  return (
    <section className="result-card result-card--amber" aria-labelledby="partial-heading">
      <header className="result-header">
        <span className="outcome-badge badge-amber">Partial result</span>
        <span>{returnedCount} of {Object.keys(analysis.workers).length} investigations returned</span>
      </header>
      <div className="result-body">
        <h2 id="partial-heading">One investigation did not return. The other one still stands.</h2>
        <p>The hydrometeorology evidence completed, validated, and was kept. The surface-water and terrain investigation became unavailable during processing, so it contributes no evidence to this result.</p>
        <div className="evidence-grid">
          <section className="evidence-panel">
            <h3><StatusOrb status="ready" />Kept — hydrometeorology</h3>
            <dl className="evidence-list">{briefing?.metrics.map((metric) => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl>
          </section>
          <section className="evidence-panel">
            <h3><StatusOrb status="down" />Missing — surface water &amp; terrain</h3>
            <ul className="missing-evidence">
              <li>Candidate surface water <span>Not available</span></li>
              <li>DEM terrain context <span>Not available</span></li>
              <li>HAND context <span>Not available</span></li>
            </ul>
          </section>
        </div>
        <AnalystReviewBanner conditions={analysis.reviewConditions} />
        {notAssessable.length > 0 && <p className="unassessed-note"><strong>{notAssessable.map((condition) => condition.id).join(", ")} — Not assessable.</strong> These conditions depend on missing evidence and have not been treated as passing.</p>}
        <div className="result-actions">
          {briefing && <DownloadBriefingButton briefing={briefing} />}
          <Button variant="outline" onClick={onRetry} disabled={retrying}><RefreshCw size={15} aria-hidden="true" />{retrying ? "Retrying investigation…" : "Retry Surface Water & Terrain"}</Button>
          {briefing && <Link className="text-action" href={`/session/${analysis.id}/briefing`}>Open partial briefing <ArrowUpRight size={14} aria-hidden="true" /></Link>}
        </div>
      </div>
    </section>
  );
}
