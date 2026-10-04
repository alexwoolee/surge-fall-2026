/** Server-only transport. Imported exclusively by the Route Handler and tests. */
const ID = "[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const session = new RegExp(`^sessions/${ID}$`, "i");
const retry = new RegExp(`^sessions/${ID}/retry$`, "i");
const briefing = new RegExp(`^sessions/${ID}/briefing$`, "i");
const loopback = (host: string) => ["localhost", "127.0.0.1", "[::1]"].includes(host);
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const fail = (status: number) => Response.json({ error: "Control request could not be completed." }, { status, headers });
async function boundedBytes(body: ReadableStream<Uint8Array> | null, limit: number, signal: AbortSignal): Promise<Uint8Array> {
  if (!body) return new Uint8Array();
  const reader = body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  const abort = () => { void reader.cancel().catch(() => undefined); };
  signal.addEventListener("abort", abort, { once: true });
  try {
    signal.throwIfAborted();
    while (true) {
      const { done, value } = await reader.read(); signal.throwIfAborted(); if (done) break;
      size += value.byteLength;
      if (size > limit) { await reader.cancel(); throw new Error("Body exceeds limit"); }
      chunks.push(value);
    }
  } finally { signal.removeEventListener("abort", abort); reader.releaseLock(); }
  const result = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
  return result;
}
export async function proxyControl(request: Request, path: string[], options: { env?: Record<string, string | undefined>; fetcher?: typeof fetch } = {}): Promise<Response> {
  const env = options.env ?? process.env;
  // Independent of the global viewer guard: a viewer process never gains operator access.
  if (env.MESHMIND_UI_MODE === "viewer") return fail(403);
  const fetcher = options.fetcher ?? fetch;
  const deadline = AbortSignal.any([request.signal, AbortSignal.timeout(12000)]);
  const route = path.join("/"); const isPost = request.method === "POST";
  const isHtml = briefing.test(route);
  if (request.method !== "GET" && !isPost) return fail(405);
  if (!(isPost ? route === "sessions" || retry.test(route) : route === "config" || route === "sessions" || session.test(route) || isHtml)) return fail(404);
  const incoming = new URL(request.url);
  // Next may normalize request.url to its listening address. Validate the actual
  // browser authority too, including for GET, so DNS rebinding cannot read data.
  const authority = request.headers.get("host");
  let browserOrigin: string;
  try {
    if (!authority || /[\s/\\@?#%,]/.test(authority) || !["http:", "https:"].includes(incoming.protocol)) return fail(403);
    const browser = new URL(`${incoming.protocol}//${authority}`);
    if (!loopback(incoming.hostname) || !loopback(browser.hostname) || browser.host !== authority.toLowerCase()
      || browser.port !== incoming.port || incoming.search) return fail(403);
    browserOrigin = browser.origin;
  } catch { return fail(403); }
  if (request.headers.get("sec-fetch-site") === "cross-site") return fail(403);
  if (isPost && (request.headers.get("origin") !== browserOrigin || request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json")) return fail(403);
  let target: URL;
  try {
    target = new URL(env.MESHMIND_CONTROL_API_URL || "http://127.0.0.1:8001");
    if (!["http:", "https:"].includes(target.protocol) || !loopback(target.hostname) || target.username || target.password || target.pathname !== "/" || target.search || target.hash) return fail(503);
  } catch { return fail(503); }
  let body: Uint8Array | undefined;
  if (isPost) {
    try { body = await boundedBytes(request.body, 20_000, deadline); } catch { return fail(413); }
    try {
      const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
      if (!value || typeof value !== "object" || Array.isArray(value)) return fail(400);
      const keys = Object.keys(value).sort().join(",");
      if (typeof value.requestId !== "string" || !new RegExp(`^${ID}$`, "i").test(value.requestId)) return fail(400);
      if (route === "sessions" ? keys !== "prompt,requestId" || typeof value.prompt !== "string" || !value.prompt.trim() || value.prompt.length > 4000 || new TextEncoder().encode(value.prompt.trim()).length > 4096 : keys !== "requestId,worker" || !["hydro", "flood", "dam"].includes(value.worker)) return fail(400);
    } catch { return fail(400); }
  }
  target.pathname = `/${route}`;
  try {
    const response = await fetcher(target, { method: request.method, redirect: "error", cache: "no-store", signal: deadline, headers: { Accept: isHtml ? "text/html" : "application/json", ...(isPost ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: body as BodyInit } : {}) });
    if (!response.ok) { await response.body?.cancel(); return fail([400, 401, 403, 404, 409, 422, 429, 503].includes(response.status) ? response.status : 502); }
    if (isPost ? response.status !== 202 : response.status !== 200) { await response.body?.cancel(); return fail(502); }
    const type = response.headers.get("content-type")?.split(";")[0].trim().toLowerCase();
    if (type !== (isHtml ? "text/html" : "application/json")) { await response.body?.cancel(); return fail(502); }
    const bytes = await boundedBytes(response.body, 4 * 1024 * 1024, deadline);
    return new Response(bytes as BodyInit, { status: response.status, headers: { ...headers, "Content-Type": isHtml ? "text/html; charset=utf-8" : "application/json", ...(isHtml ? { "Content-Disposition": `attachment; filename="amalga-${path[1]}-briefing.html"`, "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox" } : {}) } });
  } catch { return fail(502); }
}
