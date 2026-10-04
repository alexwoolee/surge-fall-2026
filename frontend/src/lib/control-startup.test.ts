import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { browserCommand, monitorDashboard, parseControlArgs, probeDashboard } from "../../scripts/start-control.mjs";

const settle = () => new Promise((resolve) => setImmediate(resolve));
const URL = "http://127.0.0.1:3000";
function fixture(overrides = {}) {
  const output: string[] = [], opened: string[] = [];
  let calls = 0, alive = true;
  const monitor = monitorDashboard({ url: URL, autoOpen: true, isAlive: () => alive, write: (text: string) => output.push(text), probe: async () => { calls++; return true; }, open: async (url: string) => { opened.push(url); return true; }, ...overrides });
  return { monitor, output, opened, calls: () => calls, exit: () => { alive = false; monitor.stop(); } };
}

test("both npm entry points use the launcher and custom ports remain explicit loopback binds", () => {
  const scripts = JSON.parse(readFileSync(new globalThis.URL("../../package.json", import.meta.url), "utf8")).scripts;
  assert.equal(scripts.start, "node -- scripts/start-control.mjs start");
  assert.equal(scripts.dev, "node -- scripts/start-control.mjs dev");
  assert.deepEqual(parseControlArgs(["start"], {}).args, ["start", "--hostname", "127.0.0.1", "--port", "3000"]);
  assert.equal(parseControlArgs(["start"], { PORT: "3100" }).url, "http://127.0.0.1:3100");
  const custom = parseControlArgs(["dev", "--port=3101", "-H", "::1", "--webpack", "--no-open-dashboard"], { PORT: "3100" });
  assert.equal(custom.url, "http://[::1]:3101"); assert.equal(custom.autoOpen, false);
  assert.deepEqual(custom.args, ["dev", "--hostname", "::1", "--port", "3101", "--webpack"]);
  for (const args of [["start", "--hostname", "0.0.0.0"], ["dev", "--port", "0"], ["start", "--port", "65536"], ["dev", "--port"], ["dev", "other-project"], ["start", "--experimental-https"]]) assert.throws(() => parseControlArgs(args, {}));
});
test("waits for its child's readiness line and HTTP success, then prints and opens exactly once", async () => {
  let complete!: (value: boolean) => void;
  const f = fixture({ probe: () => new Promise<boolean>((resolve) => { complete = resolve; }) });
  f.monitor.observe("Starting...\n"); await settle(); assert.equal(f.opened.length, 0);
  f.monitor.observe("\u001b[3"); f.monitor.observe("2m✓\u001b[0m Rea"); f.monitor.observe("dy in 200ms\n");
  assert.equal(f.output.length, 0); assert.equal(f.opened.length, 0);
  complete(true); await settle();
  assert.deepEqual(f.opened, [URL]); assert.deepEqual(f.output, [`Control dashboard: ${URL}\n`]);
  f.monitor.observe("✓ Ready in 300ms\n"); await settle(); assert.equal(f.opened.length, 1); f.exit();
});
test("occupied-port or startup failure never probes or opens another service", async () => {
  const f = fixture();
  f.monitor.observe("Error: listen EADDRINUSE: address already in use 127.0.0.1:3000\n"); f.exit();
  f.monitor.observe("✓ Ready in 200ms\n"); await settle();
  assert.equal(f.calls(), 0); assert.equal(f.opened.length, 0); assert.equal(f.output.length, 0);
});
test("child exit cancels readiness and ignores a late successful probe", async () => {
  let complete!: (value: boolean) => void; let signal: AbortSignal | undefined;
  const f = fixture({ probe: (_url: string, value: AbortSignal) => { signal = value; return new Promise<boolean>((resolve) => { complete = resolve; }); } });
  f.monitor.observe("✓ Ready in 200ms\n"); f.exit(); assert.equal(signal?.aborted, true);
  complete(true); await settle(); assert.equal(f.opened.length, 0); assert.equal(f.output.length, 0);
});
test("headless startup prints its custom dashboard URL without opening a browser", async () => {
  const f = fixture({ url: "http://localhost:3102", autoOpen: false });
  f.monitor.observe("✓ Ready in 200ms\n"); await settle();
  assert.deepEqual(f.output, ["Control dashboard: http://localhost:3102\n"]); assert.equal(f.opened.length, 0); f.exit();
});
test("failed readiness and browser opening preserve an explicit manual link", async () => {
  const pending = fixture({ probe: async () => false, timeoutMs: 0 });
  pending.monitor.observe("✓ Ready in 200ms\n"); await settle();
  assert.equal(pending.opened.length, 0); assert.match(pending.output.join(""), /readiness could not be confirmed.*127\.0\.0\.1:3000/); pending.exit();
  for (const open of [async () => false, async () => { throw new Error("no desktop"); }]) {
    const f = fixture({ open }); f.monitor.observe("✓ Ready in 200ms\n"); await settle();
    assert.match(f.output.join(""), /Control dashboard:/); assert.match(f.output.join(""), /could not open automatically.*127\.0\.0\.1:3000/); f.exit();
  }
});
test("browser commands are shell-free platform launchers with the URL as one argument", () => {
  assert.deepEqual(browserCommand(URL, "darwin"), ["open", [URL]]);
  assert.deepEqual(browserCommand(URL, "win32"), ["rundll32.exe", ["url.dll,FileProtocolHandler", URL]]);
  assert.deepEqual(browserCommand(URL, "linux"), ["xdg-open", [URL]]);
});
test("readiness probes only the local icon and requires an actual SVG response", async (t) => {
  const requests: string[] = []; let response = new Response(null, { headers: { "Content-Type": "image/svg+xml" } });
  t.mock.method(globalThis, "fetch", async (url: string, options: RequestInit) => { requests.push(url); assert.equal(options.method, "HEAD"); assert.equal(options.redirect, "error"); return response; });
  assert.equal(await probeDashboard(URL, new AbortController().signal), true);
  response = new Response(null, { headers: { "Content-Type": "text/html" } }); assert.equal(await probeDashboard(URL, new AbortController().signal), false);
  response = new Response(null, { status: 503 }); assert.equal(await probeDashboard(URL, new AbortController().signal), false);
  assert.deepEqual(requests, Array(3).fill(`${URL}/icon.svg`));
});
