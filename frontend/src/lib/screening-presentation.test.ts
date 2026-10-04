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

test("presentation omits only known absent rows and preserves measured zero, operational errors and raw evidence", async () => {
  const { presentBriefing } = await import("./briefing-presentation");
  const value = await screening();
  const briefing = value.briefing!;
  briefing.metrics = [{ label: "Measured rain", value: "0 mm" }, { label: "Absent product", value: "Unavailable." }];
  briefing.sourceProvenance = [
    { dataset: "Measured rainfall", access: "NASA", resources: "Exact public identifier unavailable for one or more resources; private paths and URLs are omitted.", coverage: "2007-12-09T00:00:00Z to 2007-12-09T03:00:00Z. Only part of the requested rainfall interval is available." },
    { dataset: "Absent soil", access: "NASA", resources: "Unavailable.", coverage: "The requested period predates this product." },
    { dataset: "Failed imagery", access: "Worker", resources: "Unavailable.", coverage: "The assigned worker could not authenticate with the external data provider." },
  ];
  briefing.reviewConditions = [
    { id: "R1", condition: "Assessed", observed: "0 mm", configured: "> 50 mm", status: "not-triggered" },
    { id: "R2", condition: "Unassessed", observed: "Unavailable", configured: "> 0.4", status: "not-assessable" },
  ];
  const original = JSON.stringify(briefing);
  const display = presentBriefing(briefing);
  assert.deepEqual(display.metrics, [{ label: "Measured rain", value: "0 mm" }]);
  assert.deepEqual(display.conditions.map((row) => row.id), ["R1"]);
  assert.deepEqual(display.sources.map((row) => row.dataset), ["Measured rainfall"]);
  assert.match(display.actualCoverage, /2007-12-09T03:00:00Z/);
  assert.doesNotMatch(display.actualCoverage, /Only part|predates/);
  assert.equal(display.operationalSources[0]?.dataset, "Failed imagery");
  assert.equal(JSON.stringify(briefing), original);
});

test("unknown classification remains explicit without changing report indices", async () => {
  const value = await screening();
  value.briefing!.risk = { ...risk, level: "unknown", score: null, alert: false,
    title: "Risk not assessable", summary: "Available observations do not establish an overall classification." };
  const html = renderToStaticMarkup(createElement(PartialResultCard, {
    analysis: value, onRetry: () => assert.fail("Rendering cannot dispatch work"), retrying: false,
  }));
  assert.match(html, /Risk not assessable/);
  assert.doesNotMatch(html, /role="alert"|Partial result|partial briefing/);
});

test("Amalga presentation brands generated prose while preserving the original request and resource identifiers", async () => {
  const { presentBriefing } = await import("./briefing-presentation");
  const value = await screening();
  const briefing = value.briefing!;
  briefing.originalRequest = "Original MeshMind request";
  briefing.sections = [{ id: "method", title: "MeshMind processing", paragraphs: ["MeshMind raster processing."] }];
  briefing.sourceProvenance = [{ dataset: "Checked source", access: "MeshMind processor", resources: "Exact-ID-MeshMind", coverage: "Recorded interval" }];
  const before = JSON.stringify(briefing);
  const display = presentBriefing(briefing);
  assert.equal(display.sections[0].title, "Amalga processing");
  assert.equal(display.sections[0].paragraphs[0], "Amalga raster processing.");
  assert.equal(display.sources[0].access, "Amalga processor");
  assert.equal(display.sources[0].resources, "Exact-ID-MeshMind");
  const html = renderToStaticMarkup(createElement(BriefingIntroduction, { briefing }));
  assert.match(html, /Amalga briefing/);
  assert.match(html, /Original MeshMind request/);
  assert.equal(JSON.stringify(briefing), before);
});

test("summary card keeps the AI risk visible and screening thresholds closed", async () => {
  const value = await screening();
  const html = renderToStaticMarkup(createElement(PartialResultCard, {
    analysis: value, onRetry: () => assert.fail("Rendering cannot dispatch work"), retrying: false,
  }));
  assert.match(html, /<details><summary>Technical screening checks<\/summary>/);
  assert.ok(html.indexOf(risk.summary) < html.indexOf("Technical screening checks"));
  assert.doesNotMatch(html, /<details open/);
});

test("risk prose omits only the exact routine public-product sentence and preserves substantive caveats", async () => {
  const { presentRiskText } = await import("./briefing-presentation");
  const routine = "DEM and HAND are unavailable, so local topographic screening cannot be applied here.";
  const driver = "Rainfall of 25 mm reinforces concern from recorded dam deterioration.";
  assert.equal(presentRiskText(`${driver} ${routine}`, "high"), driver);
  assert.equal(presentRiskText(`${driver} ${routine}`, "unknown"), `${driver} ${routine}`);
  assert.equal(presentRiskText(routine, "high"), routine);
  const mixed = "DEM and HAND are unavailable, while rainfall of 25 mm reinforces the recorded dam concern.";
  const dam = "Dam monitoring records are unavailable, so the structural condition is uncertain.";
  const operational = "The external data provider could not authenticate, so the worker returned no observations.";
  for (const text of [mixed, dam, operational]) assert.equal(presentRiskText(text, "high"), text);
  const value = await screening();
  value.briefing!.risk = { ...risk, basis: `${driver} ${routine}` };
  const original = JSON.stringify(value.briefing);
  const html = renderToStaticMarkup(createElement(BriefingIntroduction, { briefing: value.briefing! }));
  assert.match(html, /Rainfall of 25 mm reinforces concern/);
  assert.doesNotMatch(html, /DEM and HAND are unavailable/);
  assert.equal(JSON.stringify(value.briefing), original);
});
