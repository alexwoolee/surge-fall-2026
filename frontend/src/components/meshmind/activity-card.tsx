import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { ActivityGroup } from "@/lib/types";
import { StatusOrb } from "./agent-status";

const statusLabels = { ready: "Ready", active: "Active", down: "Down", failed: "Failed" };

export function ActivityCard({ activity, workerHref }: { activity: ActivityGroup; workerHref?: string }) {
  return (
    <article className="activity-card" aria-label={`${activity.name} activity`}>
      <div className="activity-header">
        <div className="activity-agent">
          <StatusOrb status={activity.status} />
          <h2>{activity.name} <span>· {activity.location}</span></h2>
        </div>
        {workerHref ? (
          <Link className="activity-worker-link" href={workerHref} aria-label={`View ${activity.name} worker`}>
            {statusLabels[activity.status]} <ArrowUpRight size={14} aria-hidden="true" />
          </Link>
        ) : <span className={`activity-status status-${activity.status}`}>{statusLabels[activity.status]}</span>}
      </div>
      <ul className="activity-events">
        {activity.events.map((event, index) => <li className="activity-event" key={`${activity.id}-${index}`}>{event}</li>)}
      </ul>
    </article>
  );
}
