import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { stripVTControlCharacters } from "node:util";

const usage = "Use start or dev with [--no-open-dashboard] [--port PORT] [--hostname LOOPBACK]; dev also accepts --webpack, --turbopack or --turbo.";
/** @param {string[]} argv @param {Record<string, string | undefined>} [env] */
export function parseControlArgs(argv, env = process.env) {
  const [mode, ...input] = argv;
  if (!["start", "dev"].includes(mode)) throw new Error(usage);
  let port = env.PORT || "3000", host = "127.0.0.1", autoOpen = true;
  const extra = [];
  for (let i = 0; i < input.length; i++) {
    const [key, inline] = input[i].split(/=(.*)/s);
    if (key === "--no-open-dashboard" && inline === undefined) { autoOpen = false; continue; }
    if (["--port", "-p", "--hostname", "-H"].includes(key)) {
      const value = inline ?? input[++i];
      if (!value || value.startsWith("-")) throw new Error(usage);
      if (["--port", "-p"].includes(key)) port = value; else host = value;
    } else if (mode === "dev" && ["--webpack", "--turbopack", "--turbo"].includes(key) && inline === undefined) {
      extra.push(key);
    } else if (key === "--help" || key === "-h") {
      return { help: true };
    } else { throw new Error(usage); }
  }
  if (!/^[1-9]\d{0,4}$/.test(port) || Number(port) > 65535) throw new Error("Control dashboard port must be between 1 and 65535.");
  if (!["127.0.0.1", "localhost", "::1"].includes(host)) throw new Error("The Control dashboard must bind to loopback.");
  const url = `http://${host === "::1" ? "[::1]" : host}:${port}`;
  // Explicit port disables Next dev's occupied-port fallback.
  return { help: false, mode, url, autoOpen, args: [mode, "--hostname", host, "--port", port, ...extra] };
}

export function browserCommand(url, platform = process.platform) {
  if (platform === "darwin") return ["open", [url]];
  if (platform === "win32") return ["rundll32.exe", ["url.dll,FileProtocolHandler", url]];
  return ["xdg-open", [url]];
}
export function openDashboard(url) {
  return new Promise((resolveOpen) => {
    const [command, args] = browserCommand(url);
    let opener;
    try { opener = spawn(command, args, { stdio: "ignore", detached: true, shell: false }); }
    catch { resolveOpen(false); return; }
    opener.once("error", () => resolveOpen(false));
    opener.once("exit", (code) => resolveOpen(code === 0));
    opener.unref();
  });
}
export async function probeDashboard(url, signal) {
  try {
    const response = await fetch(`${url}/icon.png`, { method: "HEAD", redirect: "error", cache: "no-store", signal: AbortSignal.any([signal, AbortSignal.timeout(1500)]) });
    return response.status === 200 && response.headers.get("content-type")?.split(";")[0] === "image/png";
  } catch { return false; }
}

/** Next logs Ready after binding but before loading config. Wait for both its
 * own readiness line and its local icon route; never probe an unrelated listener. */
export function monitorDashboard({ url, autoOpen, isAlive, write, probe = probeDashboard, open = openDashboard, schedule = setTimeout, timeoutMs = 120000 }) {
  let buffer = "", started = false, stopped = false, timer;
  const controller = new AbortController();
  const alive = () => !stopped && isAlive();
  async function check(deadline) {
    if (!alive()) return;
    const ready = await probe(url, controller.signal);
    if (!alive()) return;
    if (ready) {
      write(`Control dashboard: ${url}\n`);
      if (autoOpen) {
        try { if (!await open(url)) write(`Dashboard could not open automatically. Open ${url} in a browser.\n`); }
        catch { write(`Dashboard could not open automatically. Open ${url} in a browser.\n`); }
      }
    } else if (Date.now() < deadline) {
      timer = schedule(() => { void check(deadline); }, 500);
    } else {
      write(`Dashboard readiness could not be confirmed. Once the server is ready, open ${url} in a browser.\n`);
    }
  }
  return {
    observe(chunk) {
      if (started || !alive()) return;
      buffer = (buffer + String(chunk)).slice(-4096);
      if (/(?:^|\n)\s*[✓✔]?\s*Ready in [^\r\n]+[\r\n]/.test(stripVTControlCharacters(buffer))) {
        started = true;
        void check(Date.now() + timeoutMs);
      }
    },
    stop() { stopped = true; controller.abort(); clearTimeout(timer); },
  };
}

function main() {
  const config = parseControlArgs(process.argv.slice(2));
  if (config.help) { process.stdout.write(`${usage}\n`); return; }
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const next = createRequire(import.meta.url).resolve("next/dist/bin/next");
  const child = spawn(process.execPath, ["--", next, ...config.args], { cwd: root, stdio: ["inherit", "pipe", "pipe"], shell: false });
  const monitor = monitorDashboard({ ...config, isAlive: () => child.exitCode === null && child.signalCode === null && !child.killed, write: (text) => process.stdout.write(text) });
  child.stdout.on("data", (chunk) => { process.stdout.write(chunk); monitor.observe(chunk); });
  child.stderr.on("data", (chunk) => { process.stderr.write(chunk); });
  child.on("error", () => { monitor.stop(); process.stderr.write("Control dashboard server could not start.\n"); process.exitCode = 1; });
  child.on("exit", (code, signal) => { monitor.stop(); process.exitCode = code ?? (signal === "SIGINT" ? 130 : 1); });
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => { monitor.stop(); child.kill(signal); });
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try { main(); } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
