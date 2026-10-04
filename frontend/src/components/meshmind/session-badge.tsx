import type { SessionSummary } from "@/lib/types";
export const sessionLabels: Record<SessionSummary["status"], string> = { running: "Running", "briefing-ready": "Briefing ready", partial: "Partial result", "checks-failed": "Checks failed", failed: "Failed" };
export function SessionBadge({ status }: { status: SessionSummary["status"] }) {
  return <span className={`session-badge session-badge--${status}`}><span className={`status-dot status-dot--${status}`} aria-hidden="true" /><span className={status === "running" ? "shimmer" : undefined}>{sessionLabels[status]}</span></span>;
}
