import type { ReviewCondition } from "@/lib/types";

export function AnalystReviewBanner({ conditions }: { conditions: ReviewCondition[] }) {
  const triggered = conditions.filter((condition) => condition.status === "triggered");
  if (!triggered.length) return null;

  return (
    <section className="analyst-review-banner" aria-labelledby="review-heading">
      <div className="review-title-row">
        <span className="review-indicator" aria-hidden="true" />
        <h3 id="review-heading">Analyst review recommended</h3>
        <span className="review-count">{triggered.length} of {conditions.length} configured conditions triggered</span>
      </div>
      <dl className="review-list">
        {triggered.map((condition) => (
          <div className="review-row" key={condition.id}>
            <dt>{condition.id}</dt>
            <dd>{condition.condition}<span className="review-observation">{condition.observed} · configured threshold {condition.configured}</span></dd>
          </div>
        ))}
      </dl>
      <p className="review-footnote">Configured conditions identify evidence for an analyst to review. They are not a declaration of an environmental event.</p>
    </section>
  );
}
