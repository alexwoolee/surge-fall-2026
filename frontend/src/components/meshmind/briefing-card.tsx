import Link from "next/link";
import { ArrowUpRight } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import type { AnalysisState } from "@/lib/types";
import { amalgaDisplay, presentBriefing, presentRiskText } from "@/lib/briefing-presentation";
import { AnalystReviewBanner } from "./analyst-review-banner";
import { DownloadBriefingButton } from "./download-briefing-button";
import { Outcome, StatGrid } from "./outcome";

export function BriefingCard({ analysis }: { analysis: AnalysisState }) {
  const briefing = analysis.briefing;
  if (!briefing) return null;
  const display = presentBriefing(briefing);
  const combined = briefing.sections.find((section) => section.id === "combined");
  const summary = briefing.risk ? presentRiskText(briefing.risk.summary, briefing.risk.level) : amalgaDisplay(combined?.paragraphs[0] || "Control has validated the returned evidence and prepared a combined briefing.");
  const validated = Object.values(analysis.workers).filter((worker) => worker.validated).length;
  return (
    <Outcome tone={briefing.risk?.alert ? "warning" : "success"} labelledBy="briefing-result-heading" title={amalgaDisplay(briefing.title)}
      description={analysis.isDemo ? "Briefing ready · demonstration evidence" : "Briefing ready · evidence validated by Control"}
      meta={`${validated} of ${Object.keys(analysis.workers).length} validated`}
      footer={<>
        <DownloadBriefingButton briefing={briefing} sessionId={analysis.id} label="Download briefing" />
        <Button asChild variant="outline"><Link href={`/session/${analysis.id}/briefing`}>Open full briefing <ArrowUpRight size={14} aria-hidden="true" /></Link></Button>
        {briefing.executionNotice && <span className="outcome-note">{briefing.executionNotice}</span>}
      </>}>
      {briefing.risk && <p className="outcome-text" role={briefing.risk.alert ? "alert" : undefined}><strong>{briefing.risk.level === "unknown" ? "Risk not assessable" : `${briefing.risk.level.charAt(0).toUpperCase()}${briefing.risk.level.slice(1)} risk`} · {amalgaDisplay(briefing.risk.title)}</strong></p>}
      <p className="outcome-text">{summary}</p>
      {display.metrics.length > 0 && <StatGrid items={display.metrics.slice(0, 4)} />}
      {display.conditions.some((condition) => condition.status === "triggered") && <details><summary>Technical screening checks</summary><AnalystReviewBanner conditions={display.conditions} /></details>}
    </Outcome>
  );
}
