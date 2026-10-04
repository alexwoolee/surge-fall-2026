"use client";

import { useEffect, useState } from "react";
import type { WorkerId, WorkerViewerSnapshot } from "@/lib/types";
import { followWorker } from "@/lib/viewer-polling";
import { StatusOrb } from "./agent-status";
import { StatusTimeline } from "./status-timeline";

const statusLabels = { unknown: "Not observed", ready: "Idle", active: "Active", complete: "Complete", failed: "Failed", down: "Unavailable" };
const time = (value: string) => new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeStyle: "medium", timeZone: "UTC" }).format(new Date(value));

export function WorkerFollower({ role }: { role: WorkerId }) {
  const [snapshot, setSnapshot] = useState<WorkerViewerSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => followWorker(role, { onSnapshot(value) { setSnapshot(value); setError(null); }, onError: setError }), [role]);
  const worker = snapshot?.worker;
  const session = snapshot?.session;
  const name = role === "hydro" ? "Hydrometeorology Agent" : "Surface Water & Terrain Agent";
  return <main className={`worker-page atmosphere ${error ? "viewer-stale" : ""}`}>
    <header className="worker-nav"><span className="eyebrow">Amalga · {role === "hydro" ? "Laptop 2" : "Laptop 3"}</span><span className="demo-label">Read-only worker view</span></header>
    <div className="worker-content">
      {error && <p className="viewer-warning" role="alert">{error}</p>}
      {!session || !worker ? <div className="view-empty-state" role="status"><StatusOrb status="unknown" size="lg"/><h1>{name}</h1><p>{snapshot ? "Waiting for an investigation from Control." : "Connecting to Control…"}</p><p className="muted">Keep this page open. It follows the next investigation automatically.</p></div> : <section key={session.id}>
        <p className="viewer-session-id">Shared investigation: <code>{session.id}</code><br/>Requested <time dateTime={session.createdAt}>{time(session.createdAt)} UTC</time></p>
        <div className="worker-heading"><StatusOrb status={worker.status} size="lg"/><h1>{worker.name}</h1><p>{worker.location}</p><span className={`worker-explicit-status status-${worker.status} ${worker.status === "active" && !error ? "shimmer" : ""}`} role="status">{error ? "Last observed: " : ""}{statusLabels[worker.status]}</span></div>
        <section className="worker-task-card" aria-labelledby="viewer-task-title"><header className="worker-task-header"><h2 id="viewer-task-title">{session.title}</h2><span>Coordinated by Control</span></header><StatusTimeline steps={worker.steps}/><p className="worker-summary" role="status">{worker.summary}</p></section>
        {session.status !== "running" && <p className="viewer-follow-note" role="status">Most recent investigation ended. Waiting for the next request from Control.</p>}
        {session.status === "running" && worker.returned && <p className="viewer-follow-note">This worker has returned its evidence. Control may still be waiting for the other investigation or checking results.</p>}
        <section className="worker-task-card viewer-events" aria-labelledby="viewer-events-title"><header className="worker-task-header"><h2 id="viewer-events-title">Observed activity</h2><span>Recorded by Control · UTC</span></header>
          {snapshot!.events.length ? <ol>{snapshot!.events.map((event) => <li key={event.id}><time dateTime={event.observedAt}>{time(event.observedAt)}</time><span>{event.label}</span></li>)}</ol> : <p>{worker.returned || session.status !== "running" ? "No transition timeline is retained for this earlier investigation." : "No worker activity has been observed for this investigation yet."}</p>}
        </section>
        <p className="worker-resource-note">Configured resources: {worker.resources.join(", ")}.<br/>Python produces the measurements. Fast tasks may complete between updates; activity is never stretched or replayed as live.</p>
        <p className="worker-demo-note">{session.executionNotice}{snapshot!.observedAt && <> Last observation: <time dateTime={snapshot!.observedAt}>{time(snapshot!.observedAt)} UTC</time>.</>}</p>
      </section>}
    </div>
  </main>;
}
