import { X } from "lucide-react";
import type { ValidationFailure } from "@/lib/types";

export function ValidationFailureCard({ failures }: { failures: ValidationFailure[] }) {
  return (
    <section className="result-card result-card--red" aria-labelledby="validation-heading">
      <header className="result-header">
        <span className="outcome-badge badge-red"><X size={13} aria-hidden="true" />Checks failed</span>
        <span>Result validation · Control</span>
      </header>
      <div className="result-body">
        <h2 id="validation-heading">The result returned but did not pass validation, so it was not used.</h2>
        <p>The returned evidence did not satisfy the validation requirements. It has been held back from the briefing.</p>
        <dl className="validation-reasons">
          {failures.map((failure) => <div key={failure.title}><dt>{failure.title}</dt><dd>{failure.detail}</dd></div>)}
        </dl>
        <p className="muted">Failed validation does not establish that the study area is safe or unsafe.</p>
      </div>
      <footer className="result-footer">Checked by Control · evidence must satisfy validation before it can be used</footer>
    </section>
  );
}
