import { Check, X } from "@phosphor-icons/react/ssr";
import type { WorkerStep } from "@/lib/types";
import { StatusOrb } from "./agent-status";

const stepLabels = { pending: "Pending", active: "Active", complete: "Complete", failed: "Failed" };

export function StatusTimeline({ steps }: { steps: WorkerStep[] }) {
  return (
    <ol className="status-timeline" aria-label="Worker execution steps">
      {steps.map((step) => (
        <li className={`timeline-step step-${step.state}`} key={step.id} aria-current={step.state === "active" ? "step" : undefined}>
          <span className={`step-marker marker-${step.state}`} aria-hidden="true">
            {step.state === "active" ? <StatusOrb status="active" /> : step.state === "complete" ? <Check size={13} /> : step.state === "failed" ? <X size={12} /> : null}
          </span>
          <span className="step-copy">{step.label}</span>
          <span className="step-detail">{step.detail || stepLabels[step.state]}</span>
          {step.detail && <span className="sr-only">{stepLabels[step.state]}</span>}
        </li>
      ))}
    </ol>
  );
}
