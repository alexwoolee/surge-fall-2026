import test from "node:test";
import assert from "node:assert/strict";
import { proxyControl } from "./control-proxy";
const ID = "a18b29c3-9988-47a5-a113-13937c826a89";
const env = { MESHMIND_CONTROL_API_URL: "http://127.0.0.1:8001", MESHMIND_CONTROL_API_TOKEN: "private-control-token-for-boundary-tests" };
const post = (body: object = { prompt: "Review Abbotsford", requestId: ID }, headers: Record<string, string> = {}) => new Request("http://localhost:3000/api/control/sessions", { method: "POST", headers: { Host: "localhost:3000", Origin: "http://localhost:3000", "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
test("fixed endpoint ignores credentials and returns bounded safe headers", async () => {
  const response = await proxyControl(post({}, { Authorization: "Bearer injected", Cookie: "secret-browser-cookie" }), ["sessions"], { env, fetcher: async () => { throw new Error("must validate body before forwarding"); } });
  assert.equal(response.status, 400);
  const result = await proxyControl(post(), ["sessions"], { env, fetcher: async (input, init) => {
    assert.equal(String(input), "http://127.0.0.1:8001/sessions");
    assert.equal(init?.redirect, "error"); assert.equal(init?.cache, "no-store");
    assert.deepEqual(init?.headers, { Accept: "application/json", "Content-Type": "application/json" });
    return new Response(JSON.stringify({ id: ID }), { status: 202, headers: { "Content-Type": "application/json", "Set-Cookie": "private", Authorization: "private" } });
  } });
  assert.equal(result.status, 202); assert.equal(result.headers.get("set-cookie"), null); assert.equal(result.headers.get("authorization"), null); assert.equal(result.headers.get("cache-control"), "no-store");
});
test("blocks cross-origin, invalid method/path/content, query and unconfigured upstream before fetch", async () => {
  let calls = 0; const fetcher = async () => { calls++; return Response.json({}); };
  const cases: [Request, string[], typeof env][] = [
    [post(undefined, { Origin: "https://attacker.example" }), ["sessions"], env],
    [post(undefined, { "Sec-Fetch-Site": "cross-site" }), ["sessions"], env],
    [post(undefined, { "Content-Type": "text/plain" }), ["sessions"], env],
    [new Request("http://localhost:3000/api/control/sessions?target=evil"), ["sessions"], env],
    [new Request("http://attacker.example/api/control/sessions"), ["sessions"], env],
    [post(), ["https:", "evil.example"], env],
    [post(), ["sessions", ID], env],
    [post(), ["sessions"], { ...env, MESHMIND_CONTROL_API_URL: "https://external.example" }],
    [post(), ["sessions"], { ...env, MESHMIND_CONTROL_API_URL: "http://user:pass@localhost:8001" }],
    [post({ prompt: "x", requestId: ID, workerUrl: "http://evil" }), ["sessions"], env],
  ];
  for (const [request, path, config] of cases) assert.ok((await proxyControl(request, path, { env: config, fetcher })).status >= 400);
  assert.equal(calls, 0);
});
test("upstream secrets, errors, redirects and incorrect content are not reflected", async () => {
  for (const upstream of [new Response("private details token", { status: 500 }), new Response("private details token", { status: 401 }), new Response("private details token", { status: 302, headers: { Location: "http://evil" } }), new Response("private details token", { status: 200, headers: { "Content-Type": "text/plain" } })]) {
    const response = await proxyControl(new Request("http://localhost:3000/api/control/config", { headers: { Host: "localhost:3000" } }), ["config"], { env, fetcher: async () => upstream });
    assert.ok(response.status >= 400); assert.ok(!(await response.text()).includes("private")); assert.equal(response.headers.get("location"), null);
  }
  const response = await proxyControl(post(), ["sessions"], { env, fetcher: async () => { throw new Error("secret"); } });
  assert.equal(response.status, 502); assert.ok(!(await response.text()).includes("secret"));
});
test("native HTML download has fixed filename, safe content type and no upstream cookies", async () => {
  const response = await proxyControl(new Request(`http://localhost:3000/api/control/sessions/${ID}/briefing`, { headers: { Host: "localhost:3000" } }), ["sessions", ID, "briefing"], { env, fetcher: async () => new Response("<!doctype html><title>Grounded briefing</title>", { headers: { "Content-Type": "text/html", "Content-Disposition": "inline;filename=untrusted.exe", "Set-Cookie": "secret" } }) });
  assert.equal(response.status, 200); assert.equal(response.headers.get("Content-Disposition"), `attachment; filename="meshmind-${ID}-briefing.html"`); assert.equal(response.headers.get("set-cookie"), null); assert.match(await response.text(), /Grounded briefing/);
});
test("bounds request and upstream response bodies even without Content-Length", async () => {
  let called = false;
  const tooLarge = await proxyControl(post({ prompt: "x".repeat(21000), requestId: ID }), ["sessions"], { env, fetcher: async () => { called = true; return Response.json({}); } });
  assert.equal(tooLarge.status, 413); assert.equal(called, false);
  const response = await proxyControl(new Request("http://localhost:3000/api/control/config", { headers: { Host: "localhost:3000" } }), ["config"], { env, fetcher: async () => new Response("x".repeat(4 * 1024 * 1024 + 1), { headers: { "Content-Type": "application/json" } }) });
  assert.equal(response.status, 502);
});

test("cancels a stalled request body before any upstream request", async () => {
  const controller = new AbortController(); let cancelled = false; let called = false;
  const body = new ReadableStream({ cancel() { cancelled = true; } });
  const request = new Request("http://localhost:3000/api/control/sessions", { method: "POST", headers: { Host: "localhost:3000", Origin: "http://localhost:3000", "Content-Type": "application/json" }, body, signal: controller.signal, duplex: "half" } as RequestInit);
  const result = proxyControl(request, ["sessions"], { env, fetcher: async () => { called = true; return Response.json({}); } });
  controller.abort(); assert.equal((await result).status, 413); assert.equal(called, false); assert.equal(cancelled, true);
});

test("validates real Host rather than Next-normalized URL and permits matching local aliases", async () => {
  let calls = 0;
  const fetcher = async () => { calls++; return Response.json({ id: ID }, { status: 202 }); };
  const normalized = (host: string, origin = `http://${host}`) => new Request("http://127.0.0.1:3000/api/control/sessions", { method: "POST", headers: { Host: host, Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify({ prompt: "Review Abbotsford", requestId: ID }) });
  for (const host of ["evil.example:3000", "localhost:4000", "localhost", "localhost:3000.evil.example", "localhost:3000@evil.example", "localhost:3000,evil.example", "localhost:03000", "localhost:3000/", "localhost.:3000"]) {
    assert.equal((await proxyControl(normalized(host), ["sessions"], { env, fetcher })).status, 403, host);
  }
  assert.equal((await proxyControl(new Request("http://127.0.0.1:3000/api/control/config", { headers: { Host: "evil.example:3000" } }), ["config"], { env, fetcher })).status, 403);
  assert.equal((await proxyControl(new Request("http://127.0.0.1:3000/api/control/config"), ["config"], { env, fetcher })).status, 403);
  assert.equal((await proxyControl(normalized("localhost:3000", "http://127.0.0.1:3000"), ["sessions"], { env, fetcher })).status, 403);
  assert.equal(calls, 0);
  for (const host of ["localhost:3000", "127.0.0.1:3000", "[::1]:3000"]) assert.equal((await proxyControl(normalized(host), ["sessions"], { env, fetcher })).status, 202, host);
  assert.equal(calls, 3);
});

test("every valid Control operation accepts absent or arbitrary internal credentials and defaults to loopback", async () => {
  const operations: { path: string[]; body?: object; html?: boolean }[] = [
    { path: ["config"] }, { path: ["sessions"] }, { path: ["sessions", ID] }, { path: ["sessions", ID, "briefing"], html: true },
    { path: ["sessions"], body: { prompt: "Review Abbotsford", requestId: ID } },
    { path: ["sessions", ID, "retry"], body: { worker: "hydro", requestId: ID } },
  ];
  for (const token of [undefined, "", "short", "arbitrary value", "invalid\r\nheader", "任意"]) {
    for (const operation of operations) {
      let forwarded = false;
      const req = new Request(`http://localhost:3000/api/control/${operation.path.join("/")}`, {
        method: operation.body ? "POST" : "GET", headers: { Host: "localhost:3000", Origin: "http://localhost:3000", "Content-Type": "application/json", Authorization: "arbitrary caller credentials" },
        ...(operation.body ? { body: JSON.stringify(operation.body) } : {}),
      });
      const result = await proxyControl(req, operation.path, { env: { MESHMIND_CONTROL_API_TOKEN: token }, fetcher: async (input, init) => {
        forwarded = true; assert.equal(String(input), `http://127.0.0.1:8001/${operation.path.join("/")}`);
        assert.equal(new Headers(init?.headers).get("authorization"), null);
        return operation.html ? new Response("<!doctype html><title>Briefing</title>", { headers: { "Content-Type": "text/html" } }) : Response.json({ id: ID }, { status: operation.body ? 202 : 200 });
      } });
      assert.equal(forwarded, true); assert.equal(result.status, operation.body ? 202 : 200);
    }
  }
});
