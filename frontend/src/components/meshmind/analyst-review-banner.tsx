import { Warning } from "@phosphor-icons/react/ssr";
import type { ReviewCondition } from "@/lib/types";

/** Inline callout listing triggered review conditions; renders nothing when none triggered. */
export function AnalystReviewBanner({ conditions }: { conditions: ReviewCondition[] }) {
  const triggered = conditions.filter((condition) => condition.status === "triggered");
  if (!triggered.length) return null;

  return (
    <section className="callout callout--warning" aria-labelledby="review-heading">
      <div className="callout-head">
        <Warning size={16} weight="bold" aria-hidden="true" />
        <h3 id="review-heading">Analyst review recommended</h3>
        <span className="callout-meta">{triggered.length} of {conditions.length} conditions triggered</span>
      </div>
      <ul className="rule-list">
        {triggered.map((condition) => (
          <li key={condition.id}>
            <code className="rule-id">{condition.id}</code>
            <div><p>{condition.condition}</p><span>{condition.observed} · threshold {condition.configured}</span></div>
          </li>
        ))}
      </ul>
      <p className="callout-note">Conditions flag evidence for an analyst to review. They are not a declaration of an environmental event.</p>
    </section>
  );
}
