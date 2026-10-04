import test from "node:test";
import assert from "node:assert/strict";
import { authorizeViewer, guardViewerSurface, validViewerAuthority } from "./viewer-auth";
import { proxyWorkerViewer } from "./viewer-proxy";
import { proxyControl } from "./control-proxy";
import { parseViewerSnapshot } from "./viewer-contract";
import { followWorker } from "./viewer-polling";
import { parseViewerArgs, parseViewerEnv, viewerChildEnvironment } from "../../scripts/start-viewers.mjs";
import type { WorkerViewerSnapshot } from "./types";
const ID = "a18b29c3-9988-47a5-a113-13937c826a89";
const env = { MESHMIND_UI_MODE: "viewer", MESHMIND_VIEWER_HOST: "100.100.3.5:3001", MESHMIND_VIEWER_API_URL: "http://127.0.0.1:8001", MESHMIND_VIEWER_HYDRO_TOKEN: "hydro_viewer_token_abcdefghijklmnopqrstuvwxyz", MESHMIND_VIEWER_FLOOD_TOKEN: "flood_viewer_token_abcdefghijklmnopqrstuvwxyz", MESHMIND_CONTROL_API_TOKEN: "operator_secret_must_never_be_forwarded" };
const request = (path = "/viewer/hydro", headers = {}, method = "GET") => new Request(`http://127.0.0.1:3001${path}`, { method, headers: { Host: env.MESHMIND_VIEWER_HOST, ...headers } });
const waiting: WorkerViewerSnapshot = { session: null, worker: null, observedAt: null, events: [] };
const done: WorkerViewerSnapshot = { session: { id: ID, title: "Abbotsford", createdAt: "2026-10-05T00:00:00Z", executionNotice: "Historical inputs; current execution.", status: "partial" }, worker: { id: "hydro", name: "Hydro", location: "Laptop 2", status: "complete", steps: [{ id: "processing", label: "Processing", state: "complete" }], summary: "Evidence returned", resources: ["GPM"], returned: true, validated: true }, observedAt: "2026-10-05T00:00:01Z", events: [{ id: "1", observedAt: "2026-10-05T00:00:00Z", label: "Task accepted" }, { id: "2", observedAt: "2026-10-05T00:00:01Z", label: "Evidence returned" }] };

test("viewer requires no browser credentials and selects server credentials by requested role", () => {
  for (const role of ["hydro", "flood"] as const) {
    const req = request(`/viewer/${role}`);
    assert.equal(req.headers.get("authorization"), null);
    assert.deepEqual(authorizeViewer(req, role, env), { role, token: role === "hydro" ? env.MESHMIND_VIEWER_HYDRO_TOKEN : env.MESHMIND_VIEWER_FLOOD_TOKEN });
    // Old cached browser credentials neither grant privileges nor block access.
    assert.deepEqual(authorizeViewer(request(`/viewer/${role}`, { Authorization: "Basic invalid-cached-value" }), role, env), authorizeViewer(req, role, env));
  }
  for (const [req, expected] of [[request(undefined, { Host: "evil.example:3001" }), 403], [request(undefined, { Host: "100.100.3.5:3002" }), 403], [request(undefined, { "Sec-Fetch-Site": "cross-site" }), 403], [request(undefined, {}, "POST"), 405]] as const) {
    const result = authorizeViewer(req, "hydro", env); assert.ok(result instanceof Response); assert.equal(result.status, expected); assert.equal(result.headers.get("www-authenticate"), null);
  }
  assert.equal((authorizeViewer(request(), "hydro", { ...env, MESHMIND_UI_MODE: "operator" }) as Response).status, 404);
  assert.equal((authorizeViewer(request(), "hydro", { ...env, MESHMIND_VIEWER_FLOOD_TOKEN: env.MESHMIND_VIEWER_HYDRO_TOKEN }) as Response).status, 503);
  assert.equal((authorizeViewer(request(), "hydro", { ...env, MESHMIND_VIEWER_HYDRO_TOKEN: "" }) as Response).status, 503);
});
test("viewer listener opens both read-only dashboards and assets without login while blocking operator surfaces", () => {
  for (const path of ["/viewer/hydro", "/viewer/flood", "/viewer/hydro?_rsc=opaque", "/api/viewer/hydro", "/api/viewer/flood", "/_next/static/chunks/app-123.js", "/icon.svg"]) assert.equal(guardViewerSurface(request(path), env), null, path);
  for (const path of ["/", "/history", `/session/${ID}`, "/worker/hydro", "/viewer/unknown", "/api/viewer/unknown", "/api/control/config", "/api/control/sessions", "/_next/data/build/index.json", "/_next/image?url=http://evil", "/viewer/hydro?session=anything", "/api/viewer/hydro?target=evil", "/api/viewer/hydro/retry", "/viewer/hydro/extra"]) {
    const denied = guardViewerSurface(request(path), env); assert.equal(denied?.status, 403, path); assert.equal(denied?.headers.get("www-authenticate"), null);
  }
  for (const method of ["POST", "PUT", "DELETE", "HEAD", "OPTIONS"]) assert.equal(guardViewerSurface(request("/api/viewer/hydro", {}, method), env)?.status, 405, method);
  assert.equal(guardViewerSurface(request("/"), { ...env, MESHMIND_UI_MODE: "operator" }), null);
});
test("viewer serves actual dynamic-route bundles while rejecting other encoded asset characters", () => {
  for (const segment of ["%5Brole%5D", "%5brole%5d", "[role]"]) {
    assert.equal(guardViewerSurface(request(`/_next/static/chunks/app/viewer/${segment}/page-2a4c47738cc5ac64.js`), env), null);
  }
  for (const segment of ["%2foperator", "%5coperator", "%255Brole%255D", "%41role", "role%00"]) {
    assert.equal(guardViewerSurface(request(`/_next/static/chunks/app/viewer/${segment}/page.js`), env)?.status, 403);
  }
  assert.equal(guardViewerSurface(request("/api/control/%5Bpath%5D"), env)?.status, 403);
  assert.equal(guardViewerSurface(request("/_next/static/chunks/app/viewer/%5Brole%5D/page.js", {}, "POST"), env)?.status, 405);
});
test("operator proxy independently denies viewer-mode requests even with an operator token present", async () => {
  let calls = 0;
  const response = await proxyControl(request("/api/control/sessions"), ["sessions"], { env, fetcher: async () => { calls++; return Response.json({}); } });
  assert.equal(response.status, 403); assert.equal(calls, 0);
});
test("viewer APIs need no browser login and use only the requested server-side role token upstream", async () => {
  for (const role of ["hydro", "flood"] as const) {
    const snapshot = { ...done, worker: { ...done.worker!, id: role } };
    const result = await proxyWorkerViewer(request(`/api/viewer/${role}`, { Cookie: "private-browser-cookie", Authorization: "Bearer caller-secret-must-not-be-forwarded" }), role, { env, fetcher: async (input, init) => {
      assert.equal(String(input), `http://127.0.0.1:8001/viewer/${role}`); assert.equal(init?.method, "GET"); assert.equal(init?.redirect, "error");
      assert.deepEqual(init?.headers, { Authorization: `Bearer ${role === "hydro" ? env.MESHMIND_VIEWER_HYDRO_TOKEN : env.MESHMIND_VIEWER_FLOOD_TOKEN}`, Accept: "application/json" });
      return Response.json(snapshot, { headers: { "Set-Cookie": "backend-private", "X-Secret": "private", "WWW-Authenticate": "Basic unwanted" } });
    } });
    assert.equal(result.status, 200); assert.deepEqual(await result.json(), snapshot); assert.equal(result.headers.get("set-cookie"), null); assert.equal(result.headers.get("www-authenticate"), null);
    const publicResult = await proxyWorkerViewer(request(`/api/viewer/${role}`), role, { env, fetcher: async () => Response.json(snapshot) });
    assert.equal(publicResult.status, 200); assert.equal(publicResult.headers.get("www-authenticate"), null);
  }
  for (const upstream of [new Response("secret token", { status: 401, headers: { "WWW-Authenticate": "Bearer" } }), new Response("secret token", { status: 403 }), new Response("secret token", { status: 500 }), new Response("secret token", { status: 302, headers: { Location: "http://evil" } }), Response.json({ ...waiting, token: "secret" }), new Response("x".repeat(512 * 1024 + 1), { headers: { "Content-Type": "application/json" } })]) {
    const response = await proxyWorkerViewer(request("/api/viewer/hydro"), "hydro", { env, fetcher: async () => upstream });
    assert.ok(response.status >= 400); assert.doesNotMatch(await response.text(), /secret/); assert.equal(response.headers.get("www-authenticate"), null);
  }
});
test("viewer API rechecks host, method, queries and upstream without relying on global proxy", async () => {
  let calls = 0; const fetcher = async () => { calls++; return Response.json(waiting); };
  assert.equal((await proxyWorkerViewer(request("/api/viewer/hydro", { Host: "evil.example:3001" }), "hydro", { env, fetcher })).status, 403);
  assert.equal((await proxyWorkerViewer(request("/api/viewer/hydro", {}, "POST"), "hydro", { env, fetcher })).status, 405);
  assert.equal((await proxyWorkerViewer(request("/api/viewer/hydro?target=evil"), "hydro", { env, fetcher })).status, 403);
  for (const origin of ["https://evil.example", "http://127.0.0.1:8001/operator", "http://user:pass@127.0.0.1:8001", "http://127.0.0.1:8001?token=secret"]) assert.equal((await proxyWorkerViewer(request(), "hydro", { env: { ...env, MESHMIND_VIEWER_API_URL: origin }, fetcher })).status, 503);
  assert.equal(calls, 0);
});
test("viewer contract rejects foreign roles, malformed timestamps and unprojected secrets", () => {
  assert.deepEqual(parseViewerSnapshot(waiting, "hydro"), waiting);
  assert.deepEqual(parseViewerSnapshot(done, "hydro"), done);
  for (const value of [{ ...done, worker: { ...done.worker, id: "flood" } }, { ...done, observedAt: "bad date" }, { ...done, events: [{ ...done.events[0], observedAt: null }] }, { ...done, token: "secret" }, { ...waiting, worker: done.worker }, { ...done, events: [done.events[0], done.events[0]] }]) assert.throws(() => parseViewerSnapshot(value, "hydro"));
});
test("viewer keeps following after terminal snapshots and never fabricates intermediate active states", async () => {
  const received: WorkerViewerSnapshot[] = []; const scheduled: (() => void)[] = []; let calls = 0; let cancelled = false;
  const snapshots = [waiting, done, { ...done, session: { ...done.session!, id: "b18b29c3-9988-47a5-a113-13937c826a89", status: "running" }, worker: { ...done.worker!, status: "unknown", returned: false, validated: false }, events: [] }];
  const stop = followWorker("hydro", { onSnapshot: (value) => received.push(value), onError: () => assert.fail("unexpected error"), fetcher: async () => Response.json(snapshots[calls++]), schedule(callback, delay) { assert.equal(delay, 1000); scheduled.push(callback); return () => { cancelled = true; }; } });
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  await settle(); assert.equal(calls, 1); assert.deepEqual(received[0], waiting);
  scheduled.shift()!(); await settle(); assert.equal(received[1].worker!.status, "complete"); assert.equal(received[1].events.length, 2);
  scheduled.shift()!(); await settle(); assert.equal(received[2].session!.id, snapshots[2].session!.id); assert.equal(received[2].worker!.status, "unknown");
  assert.equal(received.some((value) => value.worker?.status === "active"), false); stop(); assert.equal(cancelled, true);
});
test("viewer has no overlapping polls and aborting discards pending responses", async () => {
  let complete!: (value: Response) => void; let calls = 0; let snapshots = 0; let schedules = 0; let signal: AbortSignal | null | undefined;
  const stop = followWorker("hydro", { onSnapshot: () => { snapshots++; }, onError: () => assert.fail("cancel is silent"), fetcher: async (_input, init) => { calls++; signal = init?.signal; return new Promise((resolve) => { complete = resolve; }); }, schedule() { schedules++; return () => {}; } });
  await new Promise((resolve) => setImmediate(resolve)); assert.equal(calls, 1); assert.equal(schedules, 0);
  stop(); assert.equal(signal!.aborted, true); complete(Response.json(waiting)); await new Promise((resolve) => setImmediate(resolve)); assert.equal(snapshots, 0); assert.equal(schedules, 0);
});
test("viewer launch parser is literal, validates binding and clears inherited operator credentials", () => {
  const text = `MESHMIND_VIEWER_HYDRO_TOKEN='${env.MESHMIND_VIEWER_HYDRO_TOKEN}'\nMESHMIND_VIEWER_FLOOD_TOKEN=${env.MESHMIND_VIEWER_FLOOD_TOKEN}\n`;
  const tokens = parseViewerEnv(text); const args = parseViewerArgs(["--env-file", "../private.env", "--host", "100.100.3.5", "--port", "3001"]);
  const child = viewerChildEnvironment(args, tokens, { ...env, NODE_ENV: "test", PATH: "path", OPENAI_API_KEY: "private-key", MESHMIND_WORKER_TOKEN: "private-worker" });
  assert.equal(child.MESHMIND_UI_MODE, "viewer"); assert.equal(child.MESHMIND_VIEWER_HOST, "100.100.3.5:3001"); assert.equal(child.MESHMIND_CONTROL_API_TOKEN, ""); assert.equal(child.MESHMIND_CONTROL_API_URL, ""); assert.equal(child.OPENAI_API_KEY, ""); assert.equal(child.MESHMIND_WORKER_TOKEN, undefined);
  assert.equal(parseViewerArgs(["--env-file", "x"]).host, "127.0.0.1");
  for (const host of ["0.0.0.0", "192.168.1.2", "100.63.0.1", "100.128.0.1", "evil.example", "100.100.3.05"]) assert.throws(() => parseViewerArgs(["--env-file", "x", "--host", host]));
  for (const invalidText of ["MESHMIND_VIEWER_HYDRO_TOKEN=$(cat ~/.secret)", `${text}OPENAI_API_KEY=secret\n`, text.replace(env.MESHMIND_VIEWER_FLOOD_TOKEN, env.MESHMIND_VIEWER_HYDRO_TOKEN)]) assert.throws(() => parseViewerEnv(invalidText));
  assert.equal(validViewerAuthority("100.100.3.5:3001"), true); assert.equal(validViewerAuthority("100.100.3.5:3001@evil.example"), false);
});
