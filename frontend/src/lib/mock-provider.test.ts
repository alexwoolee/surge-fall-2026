import assert from "node:assert/strict";
import test from "node:test";
import { createMockProvider, DEMO_STORAGE_KEY } from "./mock-provider";
import type { DemoStorage } from "./mock-provider";
import { DEMO_PROMPT, DEMO_TIMING } from "./mock-data";
import { getMockBriefingDownload, renderMockBriefingHtml } from "./mock-download";

function memoryStorage(): DemoStorage {
  const entries = new Map<string, string>();
  return { getItem: (key) => entries.get(key) ?? null, setItem: (key, value) => { entries.set(key, value); } };
}

function harness(storage: DemoStorage | null = null) {
  let now = Date.parse("2026-10-03T18:00:00Z");
  const provider = createMockProvider({ now: () => now, storage, seed: false });
  return { provider, setElapsed: (elapsed: number) => { now = Date.parse("2026-10-03T18:00:00Z") + elapsed; }, now: () => now };
}

test("workers advance independently before validation, review, and a ready briefing", async () => {
  const { provider, setElapsed } = harness();
  const id = await provider.startAnalysis(DEMO_PROMPT);
  let state = await provider.getAnalysis(id);
  assert.ok(state);
  assert.equal(state.workers.hydro.status, "active");
  assert.equal(state.workers.flood.status, "active");
  assert.equal(state.briefing, null);

  setElapsed(DEMO_TIMING.hydroComplete);
  state = await provider.getAnalysis(id);
  assert.ok(state);
  assert.equal(state.workers.hydro.status, "ready");
  assert.equal(state.workers.hydro.returned, true);
  assert.equal(state.workers.flood.status, "active");
  assert.equal(state.workers.flood.returned, false);
  assert.equal(state.status, "running");

  setElapsed(DEMO_TIMING.floodComplete);
  state = await provider.getAnalysis(id);
  assert.ok(state);
  assert.equal(state.workers.flood.returned, true);
  assert.equal(state.workers.flood.validated, false);
  assert.equal(state.briefing, null);

  setElapsed(DEMO_TIMING.validating);
  state = await provider.getAnalysis(id);
  assert.ok(state);
  assert.equal(state.phase, "validating");
  assert.equal(state.workers.hydro.validated, true);
  assert.equal(state.workers.flood.validated, true);

  setElapsed(DEMO_TIMING.reviewing);
  state = await provider.getAnalysis(id);
  assert.ok(state);
  assert.equal(state.phase, "reviewing");
  assert.equal(state.reviewConditions.filter((rule) => rule.status === "triggered").length, 2);

  setElapsed(DEMO_TIMING.ready);
  state = await provider.getAnalysis(id);
  assert.ok(state?.briefing);
  assert.equal(state.status, "briefing-ready");
  assert.equal(state.control, "ready");
  assert.equal(state.briefing.partial, false);
});

test("unreachable flood worker preserves hydro and marks missing-evidence rules not assessable", async () => {
  const { provider, setElapsed } = harness();
  const id = await provider.startAnalysis(DEMO_PROMPT, "partial");
  setElapsed(DEMO_TIMING.floodDown);
  let state = await provider.getAnalysis(id);
  assert.ok(state);
  assert.equal(state.workers.hydro.status, "active");
  assert.equal(state.workers.flood.status, "down");
  assert.equal(state.workers.flood.steps.find((step) => step.id === "sar")?.state, "failed");
  assert.equal(state.workers.flood.steps.find((step) => step.id === "terrain")?.state, "pending");

  setElapsed(DEMO_TIMING.ready);
  state = await provider.getAnalysis(id);
  assert.ok(state?.briefing);
  assert.equal(state.status, "partial");
  assert.equal(state.workers.hydro.validated, true);
  assert.equal(state.workers.flood.returned, false);
  assert.equal(state.briefing.partial, true);
  assert.deepEqual(state.reviewConditions.filter((rule) => rule.status === "not-assessable").map((rule) => rule.id), ["R-04", "R-05"]);
  assert.ok(state.briefing.sections.find((section) => section.id === "surface-water")?.title.includes("not available"));
  assert.ok(state.briefing.metrics.every((metric) => !metric.label.toLowerCase().includes("water extent")));
});

test("retry dispatches only flood and preserves the validated hydro result throughout", async () => {
  const { provider, setElapsed } = harness();
  const id = await provider.startAnalysis(DEMO_PROMPT, "partial");
  setElapsed(DEMO_TIMING.ready);
  const before = await provider.getAnalysis(id);
  assert.ok(before?.briefing);
  const keptMetrics = before.briefing.metrics;
  await provider.retryWorker(id, "flood");
  const retry = await provider.getAnalysis(id);
  assert.ok(retry);
  assert.equal(retry.retrying, true);
  assert.equal(retry.workers.hydro.status, "ready");
  assert.equal(retry.workers.hydro.validated, true);
  assert.equal(retry.workers.flood.status, "active");
  assert.ok(retry.workers.hydro.steps.every((step) => step.state === "complete"));
  assert.equal(retry.activities.find((group) => group.id === "hydro")?.events[0], "Previously completed hydrometeorology evidence retained.");
  setElapsed(DEMO_TIMING.ready * 2);
  const finished = await provider.getAnalysis(id);
  assert.ok(finished?.briefing);
  assert.equal(finished.status, "briefing-ready");
  assert.deepEqual(finished.briefing.metrics, keptMetrics);
  assert.equal(finished.briefing.partial, false);
});

test("invalid returned evidence is distinguished from missing evidence and cannot produce a briefing", async () => {
  const { provider, setElapsed } = harness();
  const id = await provider.startAnalysis(DEMO_PROMPT, "validation-failed");
  setElapsed(DEMO_TIMING.ready);
  const state = await provider.getAnalysis(id);
  assert.ok(state);
  assert.equal(state.status, "checks-failed");
  assert.equal(state.workers.flood.returned, true);
  assert.equal(state.workers.flood.validated, false);
  assert.equal(state.workers.flood.status, "failed");
  assert.equal(state.workers.flood.steps.find((step) => step.id === "return")?.state, "complete");
  assert.equal(state.workers.flood.steps.find((step) => step.id === "validation")?.state, "failed");
  assert.equal(state.workers.hydro.validated, true);
  assert.equal(state.validationFailures.length, 2);
  assert.equal(state.briefing, null);
  assert.deepEqual(state.reviewConditions, []);
  await assert.rejects(provider.retryWorker(id, "flood"), /Only a partial/);
});

test("dispatch failure returns no successful worker evidence or briefing", async () => {
  const { provider, setElapsed } = harness();
  const id = await provider.startAnalysis(DEMO_PROMPT, "failed");
  setElapsed(DEMO_TIMING.ready);
  const state = await provider.getAnalysis(id);
  assert.ok(state);
  assert.equal(state.status, "failed");
  assert.equal(state.workers.hydro.returned, false);
  assert.equal(state.workers.flood.returned, false);
  assert.equal(state.briefing, null);
});

test("browser reload and a second worker view share persisted runs and retries", async () => {
  const storage = memoryStorage();
  const { provider, setElapsed, now } = harness(storage);
  const id = await provider.startAnalysis(DEMO_PROMPT, "partial");
  setElapsed(DEMO_TIMING.ready);
  const reloaded = createMockProvider({ now, storage, seed: false });
  assert.equal((await reloaded.getAnalysis(id))?.status, "partial");
  await reloaded.retryWorker(id, "flood");
  assert.equal((await provider.getAnalysis(id))?.retrying, true);
  setElapsed(DEMO_TIMING.ready * 2);
  assert.equal((await provider.getAnalysis(id))?.status, "briefing-ready");
  assert.equal((await reloaded.listSessions())[0].id, id);
});

test("malformed persisted data and unavailable storage do not prevent demo use", async () => {
  const storage = memoryStorage();
  storage.setItem(DEMO_STORAGE_KEY, "{malformed");
  const { provider } = harness(storage);
  assert.deepEqual(await provider.listSessions(), []);
  const id = await provider.startAnalysis(DEMO_PROMPT);
  assert.ok(await provider.getAnalysis(id));
  const blocked: DemoStorage = { getItem() { throw new Error("Storage blocked"); }, setItem() { throw new Error("Storage blocked"); } };
  const isolated = harness(blocked);
  const isolatedId = await isolated.provider.startAnalysis(DEMO_PROMPT);
  isolated.setElapsed(DEMO_TIMING.ready);
  assert.equal((await isolated.provider.getAnalysis(isolatedId))?.status, "briefing-ready");
});

test("quota failure cannot replace a new in-memory run with an older persisted snapshot", async () => {
  const backing = memoryStorage();
  const starter = harness(backing);
  await starter.provider.startAnalysis("First investigation");
  const quotaStorage: DemoStorage = { getItem: backing.getItem, setItem() { throw new Error("Quota reached"); } };
  const { provider } = harness(quotaStorage);
  const id = await provider.startAnalysis("Second investigation");
  assert.ok(await provider.getAnalysis(id));
  assert.equal((await provider.listSessions()).length, 2);
});

test("out-of-range stored timestamps are rejected before rendering dates", async () => {
  const storage = memoryStorage();
  storage.setItem(DEMO_STORAGE_KEY, JSON.stringify({ version: 1, records: [{ id: "bad-date", title: "Invalid", prompt: "Invalid", area: "Invalid", createdAt: 1e99, startedAt: 0, scenario: "happy" }] }));
  const { provider } = harness(storage);
  assert.deepEqual(await provider.listSessions(), []);
  assert.equal(await provider.getAnalysis("bad-date"), null);
});

test("seeded history is stable, covers outcomes, and offers a static running example", async () => {
  let now = Date.parse("2026-10-03T18:00:00Z");
  const provider = createMockProvider({ now: () => now, storage: null });
  const history = await provider.listSessions();
  assert.deepEqual(new Set(history.map((session) => session.status)), new Set(["running", "briefing-ready", "partial", "checks-failed", "failed"]));
  const before = await provider.getAnalysis("running");
  now += 60_000;
  assert.deepEqual((await provider.getAnalysis("running"))?.workers, before?.workers);
  assert.equal(await provider.getAnalysis("does-not-exist"), null);
  await assert.rejects(provider.startAnalysis("  "), /Enter an environmental question/);
});

test("download contains the same partial evidence and safely escapes user text", async () => {
  const { provider, setElapsed } = harness();
  const maliciousPrompt = '<script>alert("unsafe")</script> & a rainfall question';
  const id = await provider.startAnalysis(maliciousPrompt, "partial");
  setElapsed(DEMO_TIMING.ready);
  const state = await provider.getAnalysis(id);
  assert.ok(state?.briefing);
  const html = renderMockBriefingHtml(state.briefing);
  assert.ok(html.startsWith("<!doctype html>"));
  assert.ok(html.includes("&lt;script&gt;alert(&quot;unsafe&quot;)&lt;/script&gt;"));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("Not assessable"));
  assert.ok(html.includes("Partial briefing"));
  assert.ok(html.includes(state.briefing.disclaimer));
  assert.ok(html.includes("Simulated workflow"));
  assert.ok(!html.includes("yields a candidate surface-water extent"));
});

test("native download data URI decodes to the exact escaped HTML and uses a partial filename", async () => {
  const { provider, setElapsed } = harness();
  const id = await provider.startAnalysis('Assess "rainfall" & <script>unsafe()</script> at 50% coverage — sample?', "partial");
  setElapsed(DEMO_TIMING.ready);
  const state = await provider.getAnalysis(id);
  assert.ok(state?.briefing);
  const download = getMockBriefingDownload(state.briefing);
  const prefix = "data:text/html;charset=utf-8,";
  assert.equal(download.filename, "meshmind-partial-briefing-demo.html");
  assert.ok(download.href.startsWith(prefix));
  const decoded = decodeURIComponent(download.href.slice(prefix.length));
  assert.equal(decoded, renderMockBriefingHtml(state.briefing));
  assert.ok(decoded.includes("&lt;script&gt;unsafe()&lt;/script&gt;"));
  assert.ok(!decoded.includes("<script>"));
  assert.ok(decoded.includes("Not assessable"));
  assert.equal(getMockBriefingDownload({ ...state.briefing, partial: false }).filename, "meshmind-briefing-demo.html");
});
