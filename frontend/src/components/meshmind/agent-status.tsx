import type { AgentAvailability } from "@/lib/types";

const labels: Record<AgentAvailability, string> = { ready: "Ready", active: "Active", down: "Down", failed: "Failed", unknown: "Not observed", complete: "Complete" };

export function StatusOrb({ status, size = "sm" }: { status: AgentAvailability; size?: "sm" | "lg" }) {
  return <span aria-hidden="true" className={`orb-wrap orb-wrap--${size} orb-wrap--${status}`}><span className={`status-orb status-orb--${status}`} /></span>;
}

export function AgentStatus({ name, location, status }: { name: string; location?: string; status: AgentAvailability }) {
  return <span className="agent-status"><StatusOrb status={status} /><span>{name}</span>{location && <span className="agent-location">{location}</span>}<span className="chip-divider" aria-hidden="true" /><strong>{labels[status]}</strong></span>;
}
