"use client";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useSessions } from "@/hooks/use-meshmind";
import { AGENTS } from "@/lib/mock-data";
import { Composer } from "./composer";
import { AgentStatus } from "./agent-status";
import { SessionBadge } from "./session-badge";

export function HomeView() {
  const { sessions, loading, error } = useSessions();
  return <div className="home-view"><div className="home-heading"><p className="eyebrow">ENVIRONMENTAL INTELLIGENCE</p><h1>What should we analyze?</h1></div><Composer/>
    <div className="home-agents"><span className="section-label">Your team</span><div className="agent-row">{Object.entries(AGENTS).map(([id,agent]) => <AgentStatus key={id} name={agent.name} location={agent.location} status="ready"/>)}</div></div>
    <p className="home-explainer">One question. Two specialist investigations. One grounded briefing.</p>
    <section className="recent-section"><div className="section-heading"><h2>Recent investigations</h2><Link href="/history">View all <ArrowRight size={14}/></Link></div>
      {loading && <p className="muted" role="status">Loading investigations…</p>}{error && <p role="alert">{error}</p>}
      <div className="investigation-list">{sessions.slice(0,4).map((session) => <Link key={session.id} href={`/session/${session.id}`} className="investigation-row"><div><h3>{session.title}</h3><p>{session.description}</p></div><SessionBadge status={session.status}/><ArrowRight className="row-arrow" size={16}/></Link>)}</div>
      {!loading && !error && sessions.length === 0 && <p className="muted empty-history">Your investigations will appear here.</p>}
    </section>
    <p className="home-demo-note">Demo workspace · Illustrative results, ready to explore.</p>
  </div>;
}
