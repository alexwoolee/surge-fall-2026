import type { ActivityGroup } from "@/lib/types";
import { StatusOrb, availabilityLabels as statusLabels } from "./agent-status";

/** Read-only activity transcript. Worker dashboards are not reachable from the operator chat. */
export function ActivityCard({ activity }: { activity: ActivityGroup }) {
  return (
    <article className="activity-card" aria-label={`${activity.name} activity`}>
      <div className="activity-header">
        <div className="activity-agent">
          <StatusOrb status={activity.status} />
          <h2>{activity.name} <span>· {activity.location}</span></h2>
        </div>
        <span className={`activity-status status-${activity.status} ${activity.status === "active" ? "shimmer" : ""}`}>{statusLabels[activity.status]}</span>
      </div>
      <ul className="activity-events">
        {activity.events.map((event, index) => <li className="activity-event" key={`${activity.id}-${index}`}>{event}</li>)}
      </ul>
    </article>
  );
}
