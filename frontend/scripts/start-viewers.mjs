import { readFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const allowedKeys = new Set(["MESHMIND_VIEWER_HYDRO_TOKEN", "MESHMIND_VIEWER_FLOOD_TOKEN"]);
export function parseViewerEnv(text) {
  if (Buffer.byteLength(text, "utf8") > 8192) throw new Error("Viewer environment file is too large.");
  const values = {};
  for (const raw of text.replace(/^\uFEFF/, "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const match = /^(?:export\s+)?([A-Z_]+)\s*=\s*(.*)$/.exec(line);
    if (!match || !allowedKeys.has(match[1]) || Object.hasOwn(values, match[1])) throw new Error("Viewer environment file must contain each role token once, with no other settings.");
    let value = match[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    if (!/^[A-Za-z0-9_-]{32,256}$/.test(value)) throw new Error("Viewer role tokens must contain 32–256 letters, numbers, underscores, or hyphens.");
    values[match[1]] = value;
  }
  if ([...allowedKeys].some((key) => !values[key]) || values.MESHMIND_VIEWER_HYDRO_TOKEN === values.MESHMIND_VIEWER_FLOOD_TOKEN) throw new Error("Two distinct viewer role tokens are required.");
  return values;
}
export function parseViewerArgs(argv) {
  const args = { host: "127.0.0.1", port: "3001", upstream: "http://127.0.0.1:8001" }; const seen = new Set();
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i]?.replace(/^--/, ""); const value = argv[i + 1];
    if (!["env-file", "host", "port", "upstream"].includes(key) || !argv[i].startsWith("--") || !value || value.startsWith("--") || seen.has(key)) throw new Error("Use --env-file PATH [--host ADDRESS] [--port PORT] [--upstream LOOPBACK_ORIGIN].");
    seen.add(key); args[key] = value;
  }
  if (!args["env-file"]) throw new Error("Supply the private role-token file with --env-file.");
  if (!/^[1-9]\d{0,4}$/.test(args.port) || Number(args.port) > 65535) throw new Error("Viewer port is invalid.");
  if (!["127.0.0.1", "localhost", "::1"].includes(args.host)) {
    const octets = args.host.split(".");
    if (octets.length !== 4 || octets.some((part) => !/^(0|[1-9]\d{0,2})$/.test(part) || Number(part) > 255)
      || Number(octets[0]) !== 100 || Number(octets[1]) < 64 || Number(octets[1]) > 127) throw new Error("Bind viewers only to loopback or a Tailscale 100.64.0.0/10 address.");
  }
  let upstream;
  try { upstream = new URL(args.upstream); } catch { throw new Error("Viewer upstream must be a loopback origin."); }
  if (!["http:", "https:"].includes(upstream.protocol) || !["127.0.0.1", "localhost", "[::1]"].includes(upstream.hostname) || upstream.username || upstream.password || upstream.pathname !== "/" || upstream.search || upstream.hash) throw new Error("Viewer upstream must be a loopback origin.");
  args.upstream = upstream.origin;
  return args;
}
export function viewerChildEnvironment(args, tokens, inherited = process.env) {
  const env = { ...inherited };
  for (const key of Object.keys(env)) if (key.startsWith("MESHMIND_") || key.startsWith("OPENAI_") || /^(HYDRO|FLOOD)_WORKER_/.test(key)) delete env[key];
  // Defined empty values prevent Next's operator .env.local from being loaded
  // into this process. Credentials are never passed on the command line.
  return { ...env, ...tokens, MESHMIND_UI_MODE: "viewer", MESHMIND_VIEWER_HOST: `${args.host === "::1" ? "[::1]" : args.host}:${args.port}`, MESHMIND_VIEWER_API_URL: args.upstream, MESHMIND_CONTROL_API_TOKEN: "", MESHMIND_CONTROL_API_URL: "", OPENAI_API_KEY: "", OPENAI_MODEL: "", HYDRO_WORKER_TOKEN: "", FLOOD_WORKER_TOKEN: "", HYDRO_WORKER_URL: "", FLOOD_WORKER_URL: "" };
}
function main() {
  const args = parseViewerArgs(process.argv.slice(2));
  const tokens = parseViewerEnv(readFileSync(resolve(args["env-file"]), "utf8"));
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const next = createRequire(import.meta.url).resolve("next/dist/bin/next");
  const child = spawn(process.execPath, [next, "start", "--hostname", args.host, "--port", args.port], { cwd: root, env: viewerChildEnvironment(args, tokens), stdio: "inherit", shell: false });
  child.on("error", () => { process.stderr.write("Viewer server could not start. Check the local setup.\n"); process.exitCode = 1; });
  child.on("exit", (code) => { process.exitCode = code ?? 1; });
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => { child.kill(signal); });
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try { main(); } catch { process.stderr.write("Viewer startup configuration is invalid. Check the private role-token file and loopback/Tailscale addresses. No credentials were printed.\n"); process.exitCode = 1; }
}
