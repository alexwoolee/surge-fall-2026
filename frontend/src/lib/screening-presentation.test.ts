import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { BriefingIntroduction } from "../components/meshmind/briefing-introduction";
import { PartialResultCard } from "../components/meshmind/partial-result-card";
import { SessionBadge } from "../components/meshmind/session-badge";
import { createMockProvider } from "./mock-provider";
import type { AnalysisState, RiskAssessment } from "./types";

const risk: RiskAssessment = {
  level: "high", score: 70, alert: true, confidenceLevel: "moderate", confidenceScore: 0.6,
  title: "Recorded conditions warrant review",
  summary: "The available observations show elevated concern at the reservoir.",
  basis: "The records describe conditions that an engineer should review.",
  limitations: ["These observations do not establish a breach or an inundation footprint."],
};

async function screening(): Promise<AnalysisState> {
  const value = await createMockProvider({ now: () => 1_800_000_000_000, storage: null }).getAnalysis("ready");
  assert.ok(value?.briefing);
  return { ...value, id: "11111111-1111-4111-8111-111111111111", isDemo: false,
    status: "partial", risk, executionNotice: "Technical execution context.",
    briefing: { ...value.briefing, partial: true, risk, executionNotice: "Technical execution context." } };
}

test("screening introduction leads with plain-language explanation before technical context", async () => {
  const value = await screening();
  const html = renderToStaticMarkup(createElement(BriefingIntroduction, { briefing: value.briefing! }));
  assert.ok(html.indexOf(risk.summary) < html.indexOf(risk.basis));
  assert.ok(html.indexOf(risk.basis) < html.indexOf("<details>"));
  assert.ok(html.indexOf(risk.summary) < html.indexOf("Technical execution context."));
  assert.ok(html.indexOf(risk.summary) < html.indexOf("Actual data coverage"));
  assert.match(html, /role="alert"/);
  assert.match(html, /70 \/ 100/);
  assert.match(html, /not a failure probability/);
  assert.doesNotMatch(html, /<details open|Partial briefing/);
  const hostile = renderToStaticMarkup(createElement(BriefingIntroduction, {
    briefing: { ...value.briefing!, risk: { ...risk, summary: "<script>alert('unsafe')</script>" } },
  }));
  assert.doesNotMatch(hostile, /<script>/);
  assert.match(hostile, /&lt;script&gt;/);
});

test("historical dataset gaps show a normal screening card and download without partial labels", async () => {
  const value = await screening();
  const html = renderToStaticMarkup(createElement(PartialResultCard, {
    analysis: value, onRetry: () => assert.fail("Rendering cannot dispatch work"), retrying: false,
  }));
  assert.match(html, /Briefing ready/);
  assert.match(html, /Download briefing/);
  assert.match(html, /Open full briefing/);
  assert.match(html, /The available observations show elevated concern/);
  assert.doesNotMatch(html, /Partial result|partial briefing|Worker needs attention/);
});

test("an actual missing worker remains visible and retryable without a partial label", async () => {
  const value = await screening();
  value.workers.flood = { ...value.workers.flood, status: "down", returned: false, validated: false,
    summary: "The Flood worker connection failed." };
  value.retryableWorkers = ["flood"];
  const html = renderToStaticMarkup(createElement(PartialResultCard, {
    analysis: value, onRetry: () => assert.fail("Rendering cannot retry"), retrying: false,
  }));
  assert.match(html, /Worker needs attention/);
  assert.match(html, /The Flood worker connection failed/);
  assert.match(html, /Retry Surface Water/);
  assert.match(html, /Open screening briefing/);
  assert.doesNotMatch(html, /Partial result|partial briefing/);
});

test("history labels remain neutral for available reports and explicit for failures", () => {
  const available = renderToStaticMarkup(createElement(SessionBadge, { status: "partial" }));
  assert.match(available, />Review available</);
  assert.doesNotMatch(available, />Partial/);
  assert.match(renderToStaticMarkup(createElement(SessionBadge, { status: "failed" })), />Failed</);
  assert.match(renderToStaticMarkup(createElement(SessionBadge, { status: "checks-failed" })), />Checks failed</);
});
