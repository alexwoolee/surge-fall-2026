import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { StatusTimeline } from "../components/meshmind/status-timeline";
import type { WorkerStep } from "./types";
import { validateDashboardState, formatDuration, observedStages, startDashboardPolling, attachDashboardLifecycle, dashboardStatusLabel } from "../../../backend/shared/dashboard_assets/dashboard.js";
const idle = { role: "hydro", name: "Hydrometeorology Agent", status: "idle", task: null, events: [], notice: "Observed on this worker." };
const finished = { ...idle, status: "complete", task: { id: "shared-task_2026", state: "complete", receivedAt: "2026-10-05T00:00:00.123456+00:00", startedAt: "2026-10-05T00:00:00.123456+00:00", completedAt: "2026-10-05T00:00:00.361109+00:00", durationSeconds: 0.237653 }, events: [{ state: "task_received", observedAt: "2026-10-05T00:00:00.123456+00:00", label: "Task accepted" }, { state: "complete", observedAt: "2026-10-05T00:00:00.361109+00:00", label: "Worker result ready" }] };
const settle = () => new Promise((resolve) => setImmediate(resolve));
test("merged Amalga timeline keeps prior checks green across sparse snapshots and all rows green at completion", () => {
  const steps: WorkerStep[] = [
    { id: "accepted", label: "Accepted", state: "pending", detail: "Not observed" },
    { id: "processing", label: "Processing", state: "active" },
    { id: "returned", label: "Returned", state: "pending" },
  ];
  const original = structuredClone(steps);
  const running = renderToStaticMarkup(createElement(StatusTimeline, { steps }));
  assert.equal((running.match(/timeline-step step-complete/g) || []).length, 1);
  assert.equal((running.match(/timeline-step step-active/g) || []).length, 1);
  assert.equal((running.match(/timeline-step step-pending/g) || []).length, 1);
  assert.doesNotMatch(running, /Not observed/);
  const finished = renderToStaticMarkup(createElement(StatusTimeline, { steps, terminal: true }));
  assert.equal((finished.match(/timeline-step step-complete/g) || []).length, 3);
  assert.doesNotMatch(finished, /step-pending|step-active|step-failed|Not observed/);
  assert.deepEqual(steps, original);
});
test("worker dashboard accepts shared non-UUID task IDs and real microsecond timestamps", () => {
  assert.equal(validateDashboardState(idle), idle);
  assert.equal(validateDashboardState(finished), finished);
  assert.equal(formatDuration(0.237653), "237.653 ms");
  assert.equal(formatDuration(null), "Available after processing ends");
  assert.equal(formatDuration(0), "0 ms");
  assert.equal(formatDuration(0.00000001), "Less than 0.001 ms");
  for (const invalid of [{ ...idle, status: "active" }, { ...finished, token: "private" }, { ...finished, task: { ...finished.task, id: "unsafe/path" } }, { ...finished, task: { ...finished.task, startedAt: null } }, { ...finished, task: { ...finished.task, durationSeconds: -1 } }, { ...finished, events: [{ ...finished.events[0], observedAt: "bad" }] }]) assert.throws(() => validateDashboardState(invalid));
});
test("finished worker checklist completes every stage without adding Control stages", () => {
  const stages = observedStages(finished);
  assert.equal(stages.every((stage: { progress: string }) => stage.progress === "complete"), true);
  assert.equal(stages.find((stage: { state: string }) => stage.state === "complete")?.progress, "complete");
  assert.equal(stages.some((stage: { progress: string }) => stage.progress === "active"), false);
  assert.equal(stages.some((stage: { label: string }) => /validat|fusion|Control/.test(stage.label)), false);
});
test("worker checklist completes earlier rows even when events were not observed", () => {
  const acquiring = { ...finished, status: "active", task: { ...finished.task, state: "acquiring_data", completedAt: null, durationSeconds: null }, events: [] };
  assert.equal(validateDashboardState(acquiring), acquiring);
  const stages = observedStages(acquiring);
  assert.equal(stages.find((stage: { state: string }) => stage.state === "task_received")?.progress, "complete");
  assert.equal(stages.find((stage: { state: string }) => stage.state === "acquiring_data")?.progress, "active");
  assert.equal(stages.find((stage: { state: string }) => stage.state === "dataset_located")?.progress, "pending");
  assert.equal(stages.find((stage: { state: string }) => stage.state === "processing")?.progress, "pending");
  assert.equal(dashboardStatusLabel(acquiring), "Active");
});
test("terminal checklist displays success while original result states remain unchanged", () => {
  const partial = { ...finished, status: "partial", task: { ...finished.task, state: "partial" }, events: [{ state: "partial", observedAt: finished.task.completedAt, label: "Result ready" }] };
  assert.equal(validateDashboardState(partial), partial);
  assert.equal(dashboardStatusLabel(partial), "Complete");
  assert.equal(observedStages(partial).at(-1)?.label, "Result ready");
  assert.equal(observedStages(partial).at(-1)?.progress, "complete");
  assert.equal(partial.status, "partial");
  assert.equal(partial.task.state, "partial");
  const failed = { ...partial, status: "failed", task: { ...partial.task, state: "failed" }, events: [{ ...partial.events[0], state: "failed" }] };
  assert.equal(validateDashboardState(failed), failed);
  assert.equal(dashboardStatusLabel(failed), "Complete");
  assert.equal(observedStages(failed).every((stage: { progress: string }) => stage.progress === "complete"), true);
  assert.equal(failed.status, "failed");
  assert.equal(failed.task.state, "failed");
});
test("worker poller uses only same-origin public GET and follows the next task after fast completion", async () => {
  const seen: unknown[] = []; const scheduled: (() => void)[] = []; let calls = 0;
  const next = { ...finished, status: "active", task: { ...finished.task, id: "next-task", state: "task_received", startedAt: null, completedAt: null, durationSeconds: null }, events: [] };
  const values = [idle, finished, next];
  const stop = startDashboardPolling({ onState: (value: unknown) => seen.push(value), onError: () => assert.fail("unexpected error"), fetcher: async (input: string, init: RequestInit) => {
    assert.equal(input, "/dashboard/state"); assert.equal(init.method, "GET"); assert.equal(init.credentials, "omit"); assert.equal(init.redirect, "error"); assert.equal(init.headers, undefined);
    return Response.json(values[calls++]);
  }, schedule(callback: () => void, delay: number) { assert.equal(delay, 1000); scheduled.push(callback); return () => {}; } });
  await settle(); scheduled.shift()!(); await settle(); scheduled.shift()!(); await settle(); stop();
  assert.deepEqual(seen, values); assert.equal(calls, 3);
});
test("worker poller waits for an outstanding response and drops it after cancellation", async () => {
  let resolve!: (response: Response) => void; let calls = 0; let scheduled = 0; let signal: AbortSignal | undefined;
  const stop = startDashboardPolling({ onState: () => assert.fail("cancelled response"), onError: () => assert.fail("cancelled read"), fetcher: async (_input: string, init: RequestInit) => { calls++; signal = init.signal!; return new Promise<Response>((done) => { resolve = done; }); }, schedule() { scheduled++; return () => {}; } });
  await settle(); assert.equal(calls, 1); assert.equal(scheduled, 0); stop(); assert.equal(signal!.aborted, true); resolve(Response.json(idle)); await settle(); assert.equal(scheduled, 0);
});
test("worker poller retains last observation and reports stale state on malformed or oversized reads", async () => {
  const seen: unknown[] = []; let errors = 0; const scheduled: (() => void)[] = []; let calls = 0;
  const stop = startDashboardPolling({ onState: (value: unknown) => seen.push(value), onError: (message: string) => { errors++; assert.match(message, /last observed/); }, fetcher: async () => {
    calls++; return calls === 1 ? Response.json(finished) : calls === 2 ? Response.json({ invalid: true }) : new Response("x".repeat(512 * 1024 + 1), { headers: { "Content-Type": "application/json" } });
  }, schedule(callback: () => void) { scheduled.push(callback); return () => {}; } });
  await settle(); scheduled.shift()!(); await settle(); scheduled.shift()!(); await settle(); stop();
  assert.deepEqual(seen, [finished]); assert.equal(errors, 2);
});
test("standalone worker assets contain no inline scripts, external asset requests or unsafe HTML insertion", () => {
  const root = new URL("../../../backend/shared/dashboard_assets/", import.meta.url);
  const html = readFileSync(new URL("index.html", root), "utf8");
  const js = readFileSync(new URL("dashboard.js", root), "utf8");
  assert.match(html, /src="\/dashboard\/dashboard\.js"/); assert.match(html, /href="\/dashboard\/dashboard\.css"/);
  assert.doesNotMatch(html, /(?:src|href)="(?:https?:|data:)|<style\b/);
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1); assert.equal(scripts[0][2].trim(), "");
  assert.doesNotMatch(js, /innerHTML|insertAdjacentHTML|\/api\/control|\/sessions|localStorage|sessionStorage/);
});

test("worker dashboard restarts fresh polling after back-forward-cache restoration", () => {
  const target = new EventTarget(); let starts = 0; let stops = 0; let stale = 0;
  const cleanup = attachDashboardLifecycle(target, () => { starts++; return () => { stops++; }; }, () => { stale++; });
  assert.equal(starts, 1);
  target.dispatchEvent(new Event("pagehide")); assert.equal(stops, 1); assert.equal(stale, 1);
  const restored = new Event("pageshow"); Object.defineProperty(restored, "persisted", { value: true });
  target.dispatchEvent(restored); assert.equal(starts, 2);
  target.dispatchEvent(restored); assert.equal(starts, 3); assert.equal(stops, 2);
  cleanup(); assert.equal(stops, 3); target.dispatchEvent(restored); assert.equal(starts, 3);
});
