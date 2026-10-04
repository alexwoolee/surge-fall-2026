import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RiskSummary } from "../components/meshmind/risk-summary";
import { isRiskAssessment, matchingRisk } from "./risk";
import type { RiskAssessment } from "./types";

export const checkedRisk: RiskAssessment = {
  level: "high", score: 70, confidenceLevel: "moderate", confidenceScore: 0.6,
  alert: true, title: "Elevated review priority", summary: "Recorded indicators warrant review.",
  basis: "Control evaluated available owner records and environmental measurements.",
  limitations: ["Incomplete temporal coverage."],
};

test("risk contract rejects malformed scores, alert levels, confidence and extra fields", () => {
  assert.equal(isRiskAssessment(checkedRisk), true);
  assert.equal(isRiskAssessment({ ...checkedRisk, level: "unknown", score: null, alert: false }), true);
  for (const change of [
    { level: "urgent" }, { level: "constructor" }, { alert: false }, { level: "low" },
    { level: "unknown", score: 0, alert: false }, { score: null }, { score: -1 }, { score: 101 },
    { score: Infinity }, { score: NaN }, { score: "70" }, { confidenceScore: -0.1 },
    { confidenceScore: 1.01 }, { confidenceScore: NaN }, { confidenceLevel: "certain" },
    { confidenceScore: "0.6" }, { title: "" }, { limitations: [1] }, { privateDataset: "internal" },
  ]) assert.equal(isRiskAssessment({ ...checkedRisk, ...change }), false, JSON.stringify(change));
  assert.equal(matchingRisk(checkedRisk, { ...checkedRisk }), true);
  assert.equal(matchingRisk(checkedRisk, { ...checkedRisk, confidenceScore: 0.2 }), false);
  assert.equal(matchingRisk(null, undefined), true);
});

test("high and critical summaries are accessible alerts with evidence-confidence caveats", () => {
  for (const level of ["high", "critical"] as const) {
    const html = renderToStaticMarkup(createElement(RiskSummary, { risk: { ...checkedRisk, level } }));
    assert.match(html, /role="alert"/);
    assert.match(html, /Analyst attention required/);
    assert.match(html, /Evidence confidence/);
    assert.match(html, /not a failure probability/);
    assert.match(html, /not certainty that flooding or dam failure will occur/);
    assert.match(html, /Incomplete temporal coverage/);
  }
});

test("unknown risk remains not assessable, lower risks have no alert, and text is escaped", () => {
  for (const level of ["low", "moderate", "unknown"] as const) {
    const html = renderToStaticMarkup(createElement(RiskSummary, { risk: { ...checkedRisk, level, alert: false, score: level === "unknown" ? null : 10, title: '<script>alert("x")</script>' } }));
    assert.doesNotMatch(html, /role="alert"|<script>/);
    assert.match(html, /&lt;script&gt;/);
    if (level === "unknown") assert.match(html, /Not assessable/);
  }
  assert.equal(renderToStaticMarkup(createElement(RiskSummary, { risk: null })), "");
});
