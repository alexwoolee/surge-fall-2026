import test from "node:test";
import assert from "node:assert/strict";
import { validateDashboardState } from "../../../backend/shared/dashboard_assets/dashboard.js";

const idle = { role: "dam", name: "Reservoir Risk Agent", status: "idle", task: null, events: [], notice: "Observed on this worker.", risk: null };
const done = {
  ...idle, status: "complete",
  task: { id: "dam-case", state: "complete", receivedAt: "2026-10-04T00:00:00Z", startedAt: "2026-10-04T00:00:00Z", completedAt: "2026-10-04T00:00:01Z", durationSeconds: 1 },
  risk: { level: "critical", score: 90, confidenceLevel: "moderate", confidenceScore: .75, alert: true, asOf: "2019-07-31" },
};

test("dam dashboard accepts idle and completed aggregate risk without private records", () => {
  assert.equal(validateDashboardState(idle), idle);
  assert.equal(validateDashboardState(done), done);
  assert.throws(() => validateDashboardState({ ...done, records: [{ note: "private" }] }));
  assert.throws(() => validateDashboardState({ ...done, risk: { ...done.risk, inspector: "private" } }));
});

test("dam dashboard rejects inconsistent alerts, nonfinite metrics and risk on active tasks", () => {
  for (const risk of [
    { ...done.risk, alert: false }, { ...done.risk, score: Infinity },
    { ...done.risk, confidenceScore: NaN }, { ...done.risk, confidenceScore: 2 },
    { ...done.risk, asOf: "private" }, { ...done.risk, level: "certain-failure" },
  ]) assert.throws(() => validateDashboardState({ ...done, risk }));
  assert.throws(() => validateDashboardState({ ...done, status: "active", task: { ...done.task, state: "processing", completedAt: null, durationSeconds: null } }));
});

test("dam dashboard unknown coverage is not presented as an alert", () => {
  const unknown = { ...done, risk: { level: "unknown", score: null, confidenceLevel: "low", confidenceScore: 0, alert: false, asOf: "2013-01-01" } };
  assert.equal(validateDashboardState(unknown), unknown);
  assert.throws(() => validateDashboardState({ ...idle, risk: done.risk }));
});
