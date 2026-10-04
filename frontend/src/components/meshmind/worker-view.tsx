"use client";

import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import { useAnalysis } from "@/hooks/use-meshmind";
import { isDemoMode } from "@/lib/data-provider";
import type { WorkerId } from "@/lib/types";
import { StatusOrb } from "./agent-status";
import { StatusTimeline } from "./status-timeline";
import { SpaceBackground } from "./space-background";

export function WorkerView({ workerId, sessionId = isDemoMode ? "running" : "" }: { workerId: WorkerId; sessionId?: string }) {
  const { analysis, loading, error } = useAnalysis(sessionId);
  const worker = analysis?.workers[workerId];
  const workerLabel = workerId === "hydro" ? "Hydrometeorology Agent" : "Surface Water & Terrain Agent";

  return (
    <main className="worker-page atmosphere">
      <SpaceBackground />
      <header className="worker-nav">
        <Button variant="outline" asChild><Link href={sessionId ? `/session/${encodeURIComponent(sessionId)}` : "/"}><ArrowLeft size={17} aria-hidden="true" />Back to session</Link></Button>
        {!analysis?.isDemo && <span className="demo-label">{analysis?.executionMode === "review" ? "Retained evidence review" : "Investigation activity"}</span>}
      </header>
      {loading ? <div className="view-empty-state" role="status">Opening worker activity…</div> : !analysis || !worker ? <div className="view-empty-state"><h1>{workerLabel}</h1><p>{error || "The investigation for this worker is not available."}</p><Button asChild variant="outline"><Link href="/">New session</Link></Button></div> : <div className="worker-content">
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
        {!analysis.isDemo && <p className="worker-demo-note">{analysis.executionNotice}</p>}
      </div>}
    </main>
  );
}
