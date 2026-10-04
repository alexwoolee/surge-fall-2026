import Link from "next/link";
import { NotePencil } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import type { ValidationFailure } from "@/lib/types";
import { Outcome } from "./outcome";

export function ValidationFailureCard({ failures }: { failures: ValidationFailure[] }) {
  return (
    <Outcome tone="danger" labelledBy="validation-heading" title="Checks failed"
      description="A result returned but did not pass validation, so it was held back from the briefing."
      meta={`${failures.length} ${failures.length === 1 ? "issue" : "issues"}`}>
      <dl className="issue-list">
        {failures.map((failure) => <div key={failure.title}><dt>{failure.title}</dt><dd>{failure.detail}</dd></div>)}
      </dl>
      <p className="outcome-footnote">Failed validation does not establish that the study area is safe or unsafe.</p>
    </Outcome>
  );
}

export function FailedCard() {
  return (
    <Outcome tone="danger" labelledBy="failed-heading" title="Investigation failed"
      description="No validated briefing is available. The activity above shows where execution stopped."
      footer={<Button asChild variant="outline"><Link href="/"><NotePencil size={14} aria-hidden="true" />New investigation</Link></Button>} />
  );
}
