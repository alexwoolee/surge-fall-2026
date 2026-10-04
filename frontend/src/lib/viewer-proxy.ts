import { authorizeViewer, viewerFailure, viewerHeaders, type ViewerEnvironment } from "./viewer-auth";
import { parseViewerSnapshot } from "./viewer-contract";
import type { WorkerId } from "./types";

export async function proxyWorkerViewer(request: Request, role: WorkerId, options: { env?: ViewerEnvironment; fetcher?: typeof fetch } = {}): Promise<Response> {
  const env = options.env ?? process.env;
  const identity = authorizeViewer(request, role, env);
  if (identity instanceof Response) return identity;
  if (!["hydro", "flood"].includes(role) || new URL(request.url).search) return viewerFailure(403);
  let origin: URL;
  try {
    origin = new URL(env.MESHMIND_VIEWER_API_URL || "");
    if (!["http:", "https:"].includes(origin.protocol) || !["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname)
      || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash) return viewerFailure(503);
  } catch { return viewerFailure(503); }
  origin.pathname = `/viewer/${role}`;
  const signal = AbortSignal.any([request.signal, AbortSignal.timeout(10000)]);
  try {
    const upstream = await (options.fetcher ?? fetch)(origin, { method: "GET", headers: { Authorization: `Bearer ${identity.token}`, Accept: "application/json" }, cache: "no-store", redirect: "error", signal });
    if (upstream.status !== 200 || upstream.headers.get("content-type")?.split(";")[0].trim() !== "application/json") {
      await upstream.body?.cancel(); return viewerFailure(upstream.status === 401 || upstream.status === 403 ? 503 : 502);
    }
    const reader = upstream.body?.getReader();
    if (!reader) return viewerFailure(502);
    const chunks: Uint8Array[] = []; let size = 0;
    const abort = () => { void reader.cancel().catch(() => undefined); };
    signal.addEventListener("abort", abort, { once: true });
    try {
      signal.throwIfAborted();
      while (true) {
        const { done, value } = await reader.read(); signal.throwIfAborted(); if (done) break;
        size += value.byteLength;
        if (size > 512 * 1024) { await reader.cancel(); throw new Error("Response exceeds viewer limit"); }
        chunks.push(value);
      }
    } finally { signal.removeEventListener("abort", abort); reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    const snapshot = parseViewerSnapshot(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)), role);
    return Response.json(snapshot, { headers: viewerHeaders });
  } catch { return viewerFailure(502); }
}
