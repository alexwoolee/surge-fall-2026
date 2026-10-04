import type { BriefingViewModel } from "@/lib/types";
import { RiskSummary } from "./risk-summary";

export function BriefingIntroduction({ briefing }: { briefing: BriefingViewModel }) {
  return <>
    <header className="briefing-document-header">
      <p className="eyebrow">MeshMind briefing · prepared by Control on Laptop 1</p>
      <h1>{briefing.title}</h1>
      {!briefing.risk && <p className="briefing-demo-notice">{briefing.executionNotice || briefing.demoNotice}</p>}
    </header>
    <RiskSummary risk={briefing.risk} />
    {briefing.risk && <p className="briefing-demo-notice">{briefing.executionNotice || briefing.demoNotice}</p>}
    <dl className="briefing-meta">
      <div><dt>Original request · user context, not a finding</dt><dd>“{briefing.originalRequest}”</dd></div>
      <div><dt>Study area</dt><dd>{briefing.studyArea}</dd></div>
      <div><dt>Requested window</dt><dd>{briefing.requestedWindow}</dd></div>
      <div><dt>Actual data coverage</dt><dd>{briefing.actualCoverage}</dd></div>
    </dl>
  </>;
}
