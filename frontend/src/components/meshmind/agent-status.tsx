import type { AgentAvailability } from "@/lib/types";

export const availabilityLabels: Record<AgentAvailability, string> = { ready: "Ready", active: "Active", down: "Down", failed: "Failed", unknown: "Not observed", complete: "Complete" };

/** Small status dot by default; the large orb is reserved for the focused worker page. */
export function StatusOrb({ status, size = "sm" }: { status: AgentAvailability; size?: "sm" | "lg" }) {
  if (size === "sm") return <span aria-hidden="true" className={`status-dot status-dot--${status}`} />;
  return <span aria-hidden="true" className={`orb-wrap orb-wrap--lg orb-wrap--${status}`}><span className={`status-orb status-orb--${status}`} /></span>;
}

export function AgentStatus({ name, location, status }: { name: string; location?: string; status: AgentAvailability }) {
  return <span className={`agent-status agent-status--${status}`} title={location ? `${name} · ${location}` : undefined}><StatusOrb status={status} /><span>{name}</span>{location && <span className="agent-location">{location}</span>}<strong className={`status-${status}`}>{availabilityLabels[status]}</strong></span>;
}

/** Quiet inline roster for the new-session page: dot, name, and machine; status lives in the dot and tooltip. */
export function TeamRoster({ agents }: { agents: { id: string; name: string; location: string; status: AgentAvailability }[] }) {
  return <ul className="team-roster" aria-label="Agents">
    {agents.map((agent) => <li key={agent.id} title={`${agent.name} · ${agent.location} · ${availabilityLabels[agent.status]}`}>
      <StatusOrb status={agent.status} /><span>{agent.name}</span><span className="team-location">{agent.location}</span><span className="sr-only">{availabilityLabels[agent.status]}</span>
    </li>)}
  </ul>;
}
