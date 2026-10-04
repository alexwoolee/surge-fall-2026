import test from "node:test";
import assert from "node:assert/strict";
import { createApiProvider, ControlApiError, briefingDownload } from "./api-provider";
import { createMockProvider } from "./mock-provider";
import { dataProvider, isDemoMode } from "./data-provider";

const ID = "a18b29c3-9988-47a5-a113-13937c826a89";
const KEY = "10b829c3-9988-47a5-a113-13937c826a89";
const json = (value: unknown, status = 200) => Response.json(value, { status });
function memory() { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value); } }; }
async function realState() { const demo = await createMockProvider({ now: () => 1_800_000_000_000, storage: null }).getAnalysis("ready"); return { ...demo!, id: ID, isDemo: false, executionMode: "review", executionNotice: "Historical worker evidence; no new processing.", retryableWorkers: [] }; }

test("Control is the default provider and errors never return demo fixtures", async () => {
  assert.equal(isDemoMode, false);
  assert.equal(typeof dataProvider.getConfig, "function");
  const provider = createApiProvider({ fetcher: async () => { throw new Error("private backend details"); } });
  await assert.rejects(provider.listSessions(), (error) => error instanceof ControlApiError && !error.message.includes("private"));
});
test("uses same-origin contract, authoritative history/state and safe download URL", async () => {
  const state = await realState();
  const calls: { path: string; init?: RequestInit }[] = [];
  const provider = createApiProvider({ fetcher: async (input, init) => {
    calls.push({ path: String(input), init });
    if (String(input).endsWith("/config")) return json({ mode: "review", case: { case_id: "case", name: "Abbotsford", bbox: {}, requested_window: { start: "2021-11-14", end: "2021-11-16" } }, canStart: true, notice: "Retained evidence" });
    return json(String(input).endsWith(ID) ? state : { sessions: [state] });
  } });
  assert.equal((await provider.getConfig!()).mode, "review");
  assert.equal((await provider.listSessions())[0].id, ID);
  assert.equal((await provider.getAnalysis(ID))!.isDemo, false);
  assert.deepEqual(calls.map((call) => call.path), ["/api/control/config", "/api/control/sessions", `/api/control/sessions/${ID}`]);
  assert.ok(calls.every((call) => call.init?.cache === "no-store" && call.init?.credentials === "same-origin" && !JSON.stringify(call.init?.headers).includes("Authorization")));
  assert.deepEqual(briefingDownload(ID), { href: `/api/control/sessions/${ID}/briefing`, filename: `meshmind-${ID}-briefing.html` });
  assert.throws(() => briefingDownload("../../secret"));
});
test("does not automatically replay uncertain creation; explicit repeat retains key across reload", async () => {
  const storage = memory(); const bodies: unknown[] = [];
  const provider = createApiProvider({ storage, uuid: () => KEY, fetcher: async (_input, init) => { bodies.push(JSON.parse(String(init?.body))); throw new Error("connection lost after accepted"); } });
  await assert.rejects(provider.startAnalysis("Review Abbotsford"), /may have been accepted/);
  assert.equal(bodies.length, 1);
  const reloaded = createApiProvider({ storage, uuid: () => { throw new Error("must reuse key"); }, fetcher: async (_input, init) => { bodies.push(JSON.parse(String(init?.body))); return json({ id: ID }, 202); } });
  assert.equal(await reloaded.startAnalysis("Review Abbotsford"), ID);
  assert.deepEqual(bodies, [{ prompt: "Review Abbotsford", requestId: KEY }, { prompt: "Review Abbotsford", requestId: KEY }]);
});
test("targets only requested worker and preserves uncertain retry key without automatic retries", async () => {
  const calls: { path: string; body: unknown }[] = []; let attempts = 0;
  const provider = createApiProvider({ storage: null, uuid: () => KEY, fetcher: async (input, init) => { calls.push({ path: String(input), body: JSON.parse(String(init?.body)) }); if (attempts++ === 0) return json({ detail: "secret token" }, 502); return json({ id: ID }, 202); } });
  await assert.rejects(provider.retryWorker(ID, "hydro"), (error) => error instanceof ControlApiError && !error.message.includes("secret"));
  assert.equal(calls.length, 1);
  await provider.retryWorker(ID, "hydro");
  assert.deepEqual(calls[0], { path: `/api/control/sessions/${ID}/retry`, body: { worker: "hydro", requestId: KEY } });
  assert.deepEqual(calls[1], calls[0]);
});
test("rejects malformed and fixture responses instead of presenting them as live", async () => {
  const state = await realState();
  for (const invalid of [{ ...state, isDemo: true }, { ...state, workers: {} }, { ...state, retryableWorkers: ["unknown"] }, { ...state, briefing: { title: "incomplete" } }, { ...state, createdAt: "bad date" }]) {
    const provider = createApiProvider({ fetcher: async () => json(invalid) });
    await assert.rejects(provider.getAnalysis(ID), /invalid investigation/);
  }
  assert.equal(await createApiProvider({ fetcher: async () => json({}, 404) }).getAnalysis(ID), null);
});
test("forwards cancellation and validates IDs before any network access", async () => {
  const controller = new AbortController(); let called = false;
  const provider = createApiProvider({ fetcher: async (_input, init) => { called = true; assert.ok(init?.signal?.aborted); throw new DOMException("Aborted", "AbortError"); } });
  await assert.rejects(provider.getAnalysis("ready")); assert.equal(called, false);
  controller.abort(); await assert.rejects(provider.getAnalysis(ID, controller.signal), { name: "AbortError" });
});
