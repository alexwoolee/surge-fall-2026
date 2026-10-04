import Link from "next/link";
import { ArrowUpRight } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import type { AnalysisState } from "@/lib/types";
import { AnalystReviewBanner } from "./analyst-review-banner";
import { DownloadBriefingButton } from "./download-briefing-button";
import { Outcome, StatGrid } from "./outcome";

export function BriefingCard({ analysis }: { analysis: AnalysisState }) {
  const briefing = analysis.briefing;
  if (!briefing) return null;
  const combined = briefing.sections.find((section) => section.id === "combined");
  const validated = Object.values(analysis.workers).filter((worker) => worker.validated).length;

  return (
    <Outcome tone="success" labelledBy="briefing-result-heading" title={briefing.title}
      description="Briefing ready · evidence validated by Control"
      meta={`${validated} of ${Object.keys(analysis.workers).length} validated`}
      footer={<>
        <DownloadBriefingButton briefing={briefing} sessionId={analysis.id} label="Download briefing" />
        <Button asChild variant="outline"><Link href={`/session/${analysis.id}/briefing`}>Open full briefing <ArrowUpRight size={14} aria-hidden="true" /></Link></Button>
        {briefing.executionNotice && <span className="outcome-note">{briefing.executionNotice}</span>}
      </>}>
      <p className="outcome-text">{combined?.paragraphs[0] || "The specialist investigations have returned. Control has validated the evidence and prepared a combined briefing."}</p>
      <StatGrid items={briefing.metrics.slice(0, 4)} />
      <AnalystReviewBanner conditions={analysis.reviewConditions} />
    </Outcome>
  );
}
