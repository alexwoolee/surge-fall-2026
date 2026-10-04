import Link from "next/link";
import { ArrowUpRight, Check } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import type { AnalysisState } from "@/lib/types";
import { AnalystReviewBanner } from "./analyst-review-banner";
import { DownloadBriefingButton } from "./download-briefing-button";

export function BriefingCard({ analysis }: { analysis: AnalysisState }) {
  const briefing = analysis.briefing;
  if (!briefing) return null;
  const combined = briefing.sections.find((section) => section.id === "combined");

  return (
    <section className="result-card" aria-labelledby="briefing-result-heading">
      <header className="result-header">
        <span className="outcome-badge badge-green"><Check size={13} aria-hidden="true" />Briefing ready</span>
        <span>Evidence validated by Control</span>
      </header>
      <div className="result-body">
        <p className="eyebrow">Environmental analysis</p>
        <h2 id="briefing-result-heading">{briefing.title}</h2>
        <p>{combined?.paragraphs[0] || "The specialist investigations have returned. Control has validated the evidence and prepared a combined briefing."}</p>
        <dl className="briefing-metrics">{briefing.metrics.slice(0, 4).map((metric) => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl>
        <AnalystReviewBanner conditions={analysis.reviewConditions} />
        <div className="result-actions">
          <DownloadBriefingButton briefing={briefing} sessionId={analysis.id} label="Download briefing" />
          <Button asChild variant="outline"><Link href={`/session/${analysis.id}/briefing`}>Open full briefing <ArrowUpRight size={15} aria-hidden="true" /></Link></Button>
        </div>
      </div>
      {briefing.executionNotice && <footer className="result-footer">{briefing.executionNotice}</footer>}
    </section>
  );
}
