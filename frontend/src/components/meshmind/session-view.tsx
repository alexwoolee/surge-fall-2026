"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAnalysis } from "@/hooks/use-meshmind";
import { dataProvider } from "@/lib/data-provider";
import { AgentStatus } from "./agent-status";
import { ActivityCard } from "./activity-card";
import { BriefingCard } from "./briefing-card";
import { PartialResultCard } from "./partial-result-card";
import { ValidationFailureCard } from "./validation-failure-card";
import { Composer } from "./composer";
import { Reveal } from "./reveal";

export function SessionView({ id }: { id: string }) {
  const { analysis, loading, error, refresh } = useAnalysis(id);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  async function retryFlood() {
    setRetrying(true);
    setRetryError(null);
    try {
      await dataProvider.retryWorker(id, "flood");
      await refresh();
    } catch {
      setRetryError("The investigation could not be retried. Please try again.");
    } finally {
      setRetrying(false);
    }
  }

  if (loading) return <div className="view-empty-state" role="status">Opening investigation…</div>;
  if (!analysis) return <div className="view-empty-state"><h1>{error ? "Unable to open this investigation" : "Investigation not found"}</h1><p>{error || "This investigation is not saved in this browser’s demo history."}</p><Button asChild variant="outline"><Link href="/">Back to Home</Link></Button></div>;

  const phaseLabel = analysis.status === "briefing-ready" ? "Briefing ready" : analysis.status === "partial" ? "Partial result" : analysis.status === "checks-failed" ? "Checks failed" : analysis.status === "failed" ? "Investigation failed" : analysis.phase === "validating" ? "Control is validating returned evidence" : analysis.phase === "reviewing" ? "Control is evaluating review conditions" : "Specialist investigations in progress";

  return (
    <>
      <header className="view-topbar session-topbar">
        <span className="demo-label">Demo · simulated workflow</span>
        <div className="agent-status-row">
          <AgentStatus name="Control" location="Laptop 1" status={analysis.control} />
          {Object.values(analysis.workers).map((worker) => <AgentStatus key={worker.id} name={worker.name} location={worker.location} status={worker.status} />)}
        </div>
      </header>
      <div className="session-content">
        <h1 className="sr-only">{analysis.title}</h1>
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
        {analysis.status === "briefing-ready" && <Reveal><BriefingCard analysis={analysis} /></Reveal>}
        {analysis.status === "partial" && <Reveal><PartialResultCard analysis={analysis} onRetry={retryFlood} retrying={retrying || analysis.retrying} /></Reveal>}
        {retryError && <p className="inline-error" role="alert">{retryError}</p>}
        {analysis.status === "checks-failed" && <ValidationFailureCard failures={analysis.validationFailures} />}
        {analysis.status === "failed" && <section className="result-card result-card--red"><header className="result-header"><span className="outcome-badge badge-red">Failed</span></header><div className="result-body"><h2>This investigation could not be completed.</h2><p>No validated combined briefing is available for this run. The activity above records where execution stopped.</p><Button asChild variant="outline"><Link href="/"><RefreshCw size={15} aria-hidden="true" />Start another investigation</Link></Button></div></section>}
        <div className="session-composer"><Composer compact /></div>
        <Link className="text-action session-history-link" href="/history"><ArrowLeft size={14} aria-hidden="true" />All investigations</Link>
      </div>
    </>
  );
}
