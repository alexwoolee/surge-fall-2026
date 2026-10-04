import type { BriefingViewModel } from "@/lib/types";
import { amalgaDisplay, presentBriefing } from "@/lib/briefing-presentation";
import { RiskSummary } from "./risk-summary";

export function BriefingIntroduction({ briefing }: { briefing: BriefingViewModel }) {
  const display = presentBriefing(briefing);
  return <>
    <header className="briefing-document-header">
      <p className="eyebrow">Amalga briefing · prepared by Control</p>
      <h1>{amalgaDisplay(briefing.title)}</h1>
      {!briefing.risk && <p className="briefing-demo-notice">{amalgaDisplay(briefing.executionNotice || briefing.demoNotice)}</p>}
    </header>
    <RiskSummary risk={briefing.risk} />
    {briefing.risk && <p className="briefing-demo-notice">{amalgaDisplay(briefing.executionNotice || briefing.demoNotice)}</p>}
    <dl className="briefing-meta">
      <div><dt>Original request · user context, not a finding</dt><dd>“{briefing.originalRequest}”</dd></div>
      <div><dt>Study area</dt><dd>{amalgaDisplay(briefing.studyArea)}</dd></div>
      <div><dt>Requested window</dt><dd>{briefing.requestedWindow}</dd></div>
      {display.actualCoverage && <div><dt>Actual data coverage</dt><dd>{display.actualCoverage}</dd></div>}
    </dl>
  </>;
}
