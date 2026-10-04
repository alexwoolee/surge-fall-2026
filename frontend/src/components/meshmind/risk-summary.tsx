import type { RiskAssessment } from "@/lib/types";
import { amalgaDisplay, presentLimitations, presentRiskText } from "@/lib/briefing-presentation";
import { riskLabels } from "../../lib/risk";

export function RiskSummary({ risk }: { risk: RiskAssessment | null | undefined }) {
  if (!risk) return null;
  const limitations = presentLimitations(risk.limitations);
  return <section className={`risk-summary risk-summary--${risk.level}`} role={risk.alert ? "alert" : "region"} aria-label="Environmental risk assessment">
    <div className="risk-summary-heading"><span className="risk-level">{riskLabels[risk.level]} risk</span>{risk.alert && <strong>Analyst attention required</strong>}</div>
    <h2>{amalgaDisplay(risk.title)}</h2><p>{presentRiskText(risk.summary, risk.level)}</p>
    <p><strong>What this means: </strong>{presentRiskText(risk.basis, risk.level)}</p>
    <details>
      <summary>Risk index, evidence confidence and limitations</summary>
    <dl className="risk-summary-scores">
      <div><dt>Risk index</dt><dd>{risk.score === null ? "Not assessable" : `${risk.score} / 100`}</dd></div>
      <div><dt>Evidence confidence</dt><dd>{riskLabels[risk.confidenceLevel]} · {risk.confidenceScore} / 1</dd></div>
    </dl>
    <p className="risk-explanation">The risk index is a review indicator, not a failure probability. Evidence confidence describes the support available for this assessment; it is not certainty that flooding or dam failure will occur.</p>
    {limitations.length > 0 && <ul>{limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>}
    </details>
  </section>;
}
