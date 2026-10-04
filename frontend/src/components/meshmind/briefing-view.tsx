"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAnalysis } from "@/hooks/use-meshmind";
import { DownloadBriefingButton } from "./download-briefing-button";
import { RiskSummary } from "./risk-summary";

const reviewLabels = { triggered: "Review recommended", "not-triggered": "Not triggered", "not-assessable": "Not assessable" };

export function BriefingView({ id }: { id: string }) {
  const { analysis, loading, error } = useAnalysis(id);
  const briefing = analysis?.briefing;

  if (loading) return <div className="view-empty-state" role="status">Opening briefing…</div>;
  if (!briefing) return <div className="view-empty-state"><h1>{error ? "Unable to open briefing" : "No briefing available yet"}</h1><p>{error || "A briefing becomes available after Control has validated the returned evidence."}</p><Button asChild variant="outline"><Link href={`/session/${id}`}><ArrowLeft size={15} aria-hidden="true" />Back to investigation</Link></Button></div>;

  const triggered = briefing.reviewConditions.filter((condition) => condition.status === "triggered").length;

  return (
    <>
      <header className="view-topbar briefing-topbar">
        <div className="topbar-left"><span>{briefing.partial ? "Partial briefing" : briefing.risk ? "Screening briefing" : "Final briefing"}</span><span className="demo-label">{analysis?.isDemo ? "Demo evidence" : analysis?.executionMode === "review" ? "Retained evidence" : "Validated evidence"}</span></div>
        <div className="topbar-actions"><Button asChild variant="outline"><Link href={`/session/${id}`}><ArrowLeft size={14} aria-hidden="true" />Back to investigation</Link></Button><DownloadBriefingButton briefing={briefing} sessionId={id} /></div>
      </header>
      <div className="briefing-content">
        <article className="briefing-document">
          <header className="briefing-document-header">
            <p className="eyebrow">MeshMind briefing · prepared by Control on Laptop 1</p>
            <h1>{briefing.title}</h1>
            <p className="briefing-demo-notice">{briefing.executionNotice || briefing.demoNotice}</p>
          </header>
          <dl className="briefing-meta">
            <div><dt>Original request · user context, not a finding</dt><dd>“{briefing.originalRequest}”</dd></div>
            <div><dt>Study area</dt><dd>{briefing.studyArea}</dd></div>
            <div><dt>Requested window</dt><dd>{briefing.requestedWindow}</dd></div>
            <div><dt>Actual data coverage</dt><dd>{briefing.actualCoverage}</dd></div>
          </dl>
          <RiskSummary risk={briefing.risk} />
          <section className="briefing-section" aria-labelledby="briefing-measurements"><h2 id="briefing-measurements">Validated measurements</h2><dl className="briefing-metrics">{briefing.metrics.map((metric) => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl></section>
          {briefing.sections.map((section) => <section key={section.id} className="briefing-section" aria-labelledby={`briefing-${section.id}`}><h2 id={`briefing-${section.id}`}>{section.title}</h2>{section.paragraphs.map((paragraph, index) => <p key={`${section.id}-${index}`}>{paragraph}</p>)}</section>)}
          <section className="briefing-section" aria-labelledby="briefing-review">
            <h2 id="briefing-review">Analyst-review conditions — {triggered} of {briefing.reviewConditions.length} triggered</h2>
            <div className="table-scroll">
              <table className="data-table review-table">
                <caption className="sr-only">Configured review conditions and evidence</caption>
                <thead><tr><th scope="col">Rule</th><th scope="col">Condition</th><th scope="col">Observed / configured</th><th scope="col">Outcome</th></tr></thead>
                <tbody>{briefing.reviewConditions.map((condition) => <tr className={`condition-${condition.status}`} key={condition.id}><td className="mono">{condition.id}</td><td>{condition.condition}</td><td className="mono">{condition.observed}<span className="table-secondary">{condition.configured}</span></td><td>{reviewLabels[condition.status]}</td></tr>)}</tbody>
              </table>
            </div>
            <p className="briefing-note">These configured review criteria are evaluated by deterministic rules. Crossing a threshold recommends analyst review; it does not establish an environmental event. Conditions that need unavailable evidence remain not assessable.</p>
          </section>
          <section className="briefing-section" aria-labelledby="briefing-source">
            <h2 id="briefing-source">Source provenance</h2>
            <div className="table-scroll"><table className="data-table">
              <caption className="sr-only">Source datasets, access methods, resources, and actual coverage</caption>
              <thead><tr><th scope="col">Dataset</th><th scope="col">Access</th><th scope="col">Resources</th><th scope="col">Coverage used</th></tr></thead>
              <tbody>{briefing.sourceProvenance.map((source) => <tr key={source.dataset}><td>{source.dataset}</td><td className="mono">{source.access}</td><td className="mono">{source.resources}</td><td className="mono">{source.coverage}</td></tr>)}</tbody>
            </table></div>
          </section>
          <section className="briefing-section" aria-labelledby="briefing-processing">
            <h2 id="briefing-processing">Processing provenance</h2>
            <div className="table-scroll"><table className="data-table">
              <caption className="sr-only">Investigation processing provenance</caption>
              <thead><tr><th scope="col">Investigation</th><th scope="col">Executed on</th><th scope="col">Method</th><th scope="col">Duration</th></tr></thead>
              <tbody>{briefing.processingProvenance.map((process) => <tr key={process.investigation}><td>{process.investigation}</td><td>{process.location}</td><td className="mono">{process.method}</td><td className="mono">{process.duration}</td></tr>)}</tbody>
            </table></div>
            <p className="briefing-note">{analysis?.isDemo ? "Execution labels and durations are simulated for this frontend demonstration. They do not attest to work performed on remote laptops." : briefing.executionNotice || analysis?.executionNotice}</p>
          </section>
          <section className="briefing-section" aria-labelledby="briefing-limitations"><h2 id="briefing-limitations">Limitations</h2><ul className="briefing-limitations">{briefing.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></section>
          <footer className="disclaimer">{briefing.disclaimer}</footer>
        </article>
      </div>
    </>
  );
}
