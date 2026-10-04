import { Check } from "@phosphor-icons/react/ssr";
import type { WorkerStep } from "@/lib/types";
import { StatusOrb } from "./agent-status";

const stepLabels = { pending: "Pending", active: "Active", complete: "Complete", failed: "Complete" };

/** Smooth sparse progress snapshots without changing the underlying worker result. */
export function presentedSteps(steps: WorkerStep[], terminal = false): WorkerStep[] {
  const lastReached = steps.reduce((last, step, index) => step.state !== "pending" ? index : last, -1);
  const ended = terminal || steps.some((step) => step.state === "failed") || (steps.length > 0 && steps.at(-1)?.state === "complete");
  return steps.map((step, index) => ended || index < lastReached || step.state === "complete"
    ? { ...step, state: "complete", detail: "Complete" }
    : { ...step });
}

export function StatusTimeline({ steps, terminal = false }: { steps: WorkerStep[]; terminal?: boolean }) {
  return (
    <ol className="status-timeline" aria-label="Worker execution steps">
      {presentedSteps(steps, terminal).map((step) => (
        <li className={`timeline-step step-${step.state}`} key={step.id} aria-current={step.state === "active" ? "step" : undefined}>
          <span className={`step-marker marker-${step.state}`} aria-hidden="true">
            {step.state === "active" ? <StatusOrb status="active" /> : step.state === "complete" ? <Check size={13} /> : null}
          </span>
          <span className={`step-copy ${step.state === "active" ? "shimmer" : ""}`}>{step.label}</span>
          <span className={`step-detail ${step.state === "active" ? "shimmer" : ""}`}>{step.detail || stepLabels[step.state]}</span>
          {step.detail && <span className="sr-only">{stepLabels[step.state]}</span>}
        </li>
      ))}
    </ol>
  );
}
