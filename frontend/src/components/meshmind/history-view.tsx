"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Search } from "lucide-react";
import { useSessions } from "@/hooks/use-meshmind";
import { SessionBadge } from "./session-badge";
import { StatusOrb } from "./agent-status";
import { Input } from "@/components/ui/input";
import type { SessionSummary } from "@/lib/types";

function dayKey(date: Date) { return new Intl.DateTimeFormat("en-CA",{timeZone:"America/Vancouver",year:"numeric",month:"2-digit",day:"2-digit"}).format(date); }
function groupFor(session: SessionSummary, now: Date) { const day = dayKey(new Date(session.createdAt)); if(day === dayKey(now)) return "Today"; if(day === dayKey(new Date(now.getTime()-86400000))) return "Yesterday"; return "Earlier this week"; }
export function HistoryView({ search = false }: { search?: boolean }) {
  const { sessions, loading, error } = useSessions();
  const [query, setQuery] = useState("");
  const visible = sessions.filter((session) => `${session.title} ${session.description}`.toLowerCase().includes(query.toLowerCase()));
  const now = new Date();
  return <><header className="view-topbar"><div className="topbar-left"><Link href="/" className="back-link"><ArrowLeft size={16}/>Back</Link><h1>History</h1></div><span className="muted">{sessions.length} investigations</span></header><div className="history-content"><div className="history-search"><Search size={17}/><Input aria-label="Search investigations" placeholder="Search investigations…" autoFocus={search} value={query} onChange={(event) => setQuery(event.target.value)}/><span className="search-shortcut">⌘ K</span></div>
  {loading && <p role="status">Loading history…</p>}{error && <p role="alert">{error}</p>}
  {["Today","Yesterday","Earlier this week"].map((group) => { const rows = visible.filter((session) => groupFor(session,now)===group); if(!rows.length) return null; return <section className="history-group" key={group}><div className="group-heading"><h2>{group}</h2><span className="group-line"/><span>{rows.length} {rows.length===1 ? "investigation" : "investigations"}</span></div><div className="investigation-list">{rows.map((session) => <Link href={`/session/${session.id}`} key={session.id} className="investigation-row history-row"><StatusOrb status={session.status === "running" ? "active" : session.status === "briefing-ready" ? "ready" : session.status === "partial" ? "down" : "failed"}/><div><h3>{session.title}</h3><p>{session.description}</p></div><SessionBadge status={session.status}/><time dateTime={session.createdAt}>{new Intl.DateTimeFormat("en-CA",{timeZone:"America/Vancouver",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(session.createdAt))}</time></Link>)}</div></section>; })}
  {!loading && !error && !visible.length && <div className="empty-history"><h2>No investigations found</h2><p className="muted">Try a different search or start a new investigation.</p><Link className="text-action" href="/">New investigation <ArrowLeft size={14}/></Link></div>}
  </div></>;
}
