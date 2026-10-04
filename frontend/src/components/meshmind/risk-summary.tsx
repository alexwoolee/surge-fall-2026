import type { RiskAssessment } from "@/lib/types";
import { riskLabels } from "../../lib/risk";

export function RiskSummary({ risk }: { risk: RiskAssessment | null | undefined }) {
  if (!risk) return null;
  return <section className={`risk-summary risk-summary--${risk.level}`} role={risk.alert ? "alert" : "region"} aria-label="Environmental risk assessment">
    <div className="risk-summary-heading"><span className="risk-level">{riskLabels[risk.level]} risk</span>{risk.alert && <strong>Analyst attention required</strong>}</div>
    <h2>{risk.title}</h2><p>{risk.summary}</p>
    <p><strong>What this means: </strong>{risk.basis}</p>
    <details>
      <summary>Risk index, evidence confidence and limitations</summary>
    <dl className="risk-summary-scores">
      <div><dt>Risk index</dt><dd>{risk.score === null ? "Not assessable" : `${risk.score} / 100`}</dd></div>
      <div><dt>Evidence confidence</dt><dd>{riskLabels[risk.confidenceLevel]} · {risk.confidenceScore} / 1</dd></div>
    </dl>
    <p className="risk-explanation">The risk index is a review indicator, not a failure probability. Evidence confidence describes the support available for this assessment; it is not certainty that flooding or dam failure will occur.</p>
    {risk.limitations.length > 0 && <ul>{risk.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>}
    </details>
  </section>;
}
