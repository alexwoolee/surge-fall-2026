"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAnalysis } from "@/hooks/use-meshmind";
import { isDemoMode } from "@/lib/data-provider";
import type { WorkerId } from "@/lib/types";
import { WORKERS } from "@/lib/workers";
import { StatusOrb } from "./agent-status";
import { StatusTimeline } from "./status-timeline";

export function WorkerView({ workerId, sessionId = isDemoMode ? "running" : "" }: { workerId: WorkerId; sessionId?: string }) {
  const { analysis, loading, error } = useAnalysis(sessionId);
  const worker = analysis?.workers[workerId];
  const workerLabel = `${WORKERS[workerId].name} Agent`;
  const unavailable = workerId === "dam" ? analysis ? "Dam Condition was not included in this investigation. It runs only for Toddbrook Reservoir, Whaley Bridge, Derbyshire." : "Owner-record review is available only for Toddbrook Reservoir, Whaley Bridge, Derbyshire. Open a matching investigation to see its observed activity." : "The investigation for this worker is not available.";

  return (
    <main className="worker-page atmosphere">
      <div className="ambient-field" aria-hidden="true"/>
      <header className="worker-nav">
        <Button variant="outline" asChild><Link href={sessionId ? `/session/${encodeURIComponent(sessionId)}` : "/"}><ArrowLeft size={17} aria-hidden="true" />Back to session</Link></Button>
        <span className="demo-label">{analysis?.isDemo ? "Demo · simulated workflow" : analysis?.executionMode === "review" ? "Retained evidence review" : "Investigation activity"}</span>
      </header>
      {loading ? <div className="view-empty-state" role="status">Opening worker activity…</div> : !analysis || !worker ? <div className="view-empty-state"><h1>{workerLabel}</h1><p>{error || unavailable}</p><Button asChild variant="outline"><Link href="/">Back to Home</Link></Button></div> : <div className="worker-content">
        {error && <p role="alert">{error} Displaying the last received state.</p>}
        <div className="worker-heading">
          <StatusOrb status={worker.status} size="lg" />
          <h1>{worker.name}</h1>
          <p>{worker.status === "unknown" ? "Execution has not been observed" : worker.status === "active" ? `Executing tools on ${worker.location}` : worker.status === "down" ? `Not reachable on ${worker.location}` : worker.status === "failed" ? `Investigation failed on ${worker.location}` : worker.returned ? `Investigation complete on ${worker.location}` : `Ready on ${worker.location}`}</p>
          <span className={`worker-explicit-status status-${worker.status}`}>{worker.status === "unknown" ? "Not observed" : worker.status === "active" ? "Active" : worker.status === "down" ? "Down" : worker.status === "failed" ? "Failed" : worker.returned ? "Complete" : "Ready"}</span>
        </div>
        <section className="worker-task-card" aria-labelledby="worker-task-title">
          <header className="worker-task-header"><h2 id="worker-task-title">{analysis.title}</h2><span>Dispatched by Control · Laptop 1</span></header>
          <StatusTimeline steps={worker.steps} />
          <p className={`worker-summary ${worker.status === "down" || worker.status === "failed" ? "failure-detail" : ""}`} role="status">{worker.summary}</p>
        </section>
        <p className="worker-resource-note">Approved resources on this worker: {worker.resources.join(", ")}.<br />Python produces the numerical measurements; the model does not.</p>
        <p className="worker-demo-note">{analysis.isDemo ? "This frontend demonstration shows simulated activity. No remote processing is being performed." : analysis.executionNotice}</p>
      </div>}
    </main>
  );
}
