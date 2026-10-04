"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAnalysis } from "@/hooks/use-meshmind";
import { ControlApiError } from "@/lib/api-provider";
import type { WorkerId } from "@/lib/types";
import { dataProvider } from "@/lib/data-provider";
import { AgentStatus } from "./agent-status";
import { ActivityCard } from "./activity-card";
import { BriefingCard } from "./briefing-card";
import { PartialResultCard } from "./partial-result-card";
import { ValidationFailureCard } from "./validation-failure-card";
import { Composer } from "./composer";
import { Reveal } from "./reveal";
import { RiskSummary } from "./risk-summary";

export function SessionView({ id }: { id: string }) {
  const { analysis, loading, error, refresh } = useAnalysis(id);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  async function retryWorker(worker: WorkerId) {
    setRetrying(true);
    setRetryError(null);
    try {
      await dataProvider.retryWorker(id, worker);
      await refresh();
    } catch (error) {
      setRetryError(error instanceof ControlApiError ? error.message : "The investigation could not be retried.");
    } finally {
      setRetrying(false);
    }
  }

  if (loading) return <div className="view-empty-state" role="status">Opening investigation…</div>;
  if (!analysis) return <div className="view-empty-state"><h1>{error ? "Unable to open this investigation" : "Investigation not found"}</h1><p>{error || "This investigation is not available in the current Control history."}</p><Button asChild variant="outline"><Link href="/">Back to Home</Link></Button></div>;

  const phaseLabel = analysis.status === "briefing-ready" ? "Briefing ready" : analysis.status === "partial" ? analysis.risk ? "Screening briefing available" : "Partial result" : analysis.status === "checks-failed" ? "Checks failed" : analysis.status === "failed" ? "Investigation failed" : !analysis.isDemo ? analysis.description : analysis.phase === "validating" ? "Control is validating returned evidence" : analysis.phase === "reviewing" ? "Control is evaluating review conditions" : "Specialist investigations in progress";
  const workerNeedsAttention = Boolean(analysis.risk && analysis.briefing) && Object.values(analysis.workers).some((worker) => !worker.returned || !worker.validated);

  return (
    <>
      <header className="view-topbar session-topbar">
        <span className="demo-label">{analysis.isDemo ? "Demo · simulated workflow" : analysis.executionMode === "review" ? "Retained evidence review" : "Worker investigation"}</span>
        <div className="agent-status-row">
          <AgentStatus name="Control" location="Laptop 1" status={analysis.control} />
          {Object.values(analysis.workers).map((worker) => <AgentStatus key={worker.id} name={worker.name} location={worker.location} status={worker.status} />)}
        </div>
      </header>
      <div className="session-content">
        <h1 className="sr-only">{analysis.title}</h1>
        {error && <p role="alert" className="inline-error">{error} Displaying the last received state. <button onClick={refresh}>Refresh</button></p>}
        <RiskSummary risk={analysis.risk} />
        {analysis.executionNotice && <p className="execution-notice">{analysis.executionNotice}</p>}
        <p className="sr-only" role="status" aria-live="polite">{phaseLabel}</p>
        <div className="prompt-bubble"><p>{analysis.prompt}</p></div>
        <div className="context-pills"><span className="context-pill">{analysis.studyArea}</span><span className="context-pill">{analysis.requestedWindow}</span></div>
        <div className="session-activity" aria-label="Observable system activity">
          {analysis.activities.map((activity) => {
            const worker = Object.values(analysis.workers).find((candidate) => candidate.name === activity.name && candidate.location === activity.location);
            return <Reveal key={activity.id}><ActivityCard activity={activity} workerHref={worker ? `/worker/${worker.id}?session=${encodeURIComponent(id)}` : undefined} /></Reveal>;
          })}
        </div>
        {analysis.status === "running" && <div className="session-run-note"><span className="run-note-dot" aria-hidden="true" /><span>{phaseLabel}</span><span className="muted">Workers update independently</span></div>}
        {analysis.status === "briefing-ready" && !workerNeedsAttention && <Reveal><BriefingCard analysis={analysis} /></Reveal>}
        {(analysis.status === "partial" || workerNeedsAttention) && <Reveal><PartialResultCard analysis={analysis} onRetry={retryWorker} retrying={retrying || analysis.retrying} /></Reveal>}
        {analysis.status !== "partial" && !workerNeedsAttention && !analysis.retrying && analysis.retryableWorkers?.map((worker) => analysis.workers[worker] && <Button key={worker} variant="outline" onClick={() => void retryWorker(worker)} disabled={retrying}>Retry {analysis.workers[worker]?.name}</Button>)}
        {retryError && <p className="inline-error" role="alert">{retryError}</p>}
        {(analysis.status === "checks-failed" || analysis.risk && analysis.validationFailures.length > 0) && <ValidationFailureCard failures={analysis.validationFailures} />}
        {analysis.status === "failed" && <section className="result-card result-card--red"><header className="result-header"><span className="outcome-badge badge-red">Failed</span></header><div className="result-body"><h2>This investigation could not be completed.</h2><p>No validated combined briefing is available for this run. The activity above records where execution stopped.</p><Button asChild variant="outline"><Link href="/"><RefreshCw size={15} aria-hidden="true" />Start another investigation</Link></Button></div></section>}
        <div className="session-composer"><Composer compact /></div>
        <Link className="text-action session-history-link" href="/history"><ArrowLeft size={14} aria-hidden="true" />All investigations</Link>
      </div>
    </>
  );
}
