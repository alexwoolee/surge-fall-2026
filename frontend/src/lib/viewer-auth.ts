/** Node-only viewer access boundary; never import this module from client code. */
import type { WorkerId } from "./types";

export type ViewerEnvironment = Record<string, string | undefined>;
export type ViewerIdentity = { role: WorkerId; token: string };
export const viewerHeaders = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY" };
export const viewerFailure = (status: number) => new Response("Worker viewer is unavailable.", { status, headers: viewerHeaders });
const validToken = (token: string | undefined): token is string => !!token && token.length >= 32 && token.length <= 256 && /^[A-Za-z0-9_-]+$/.test(token);
export function validViewerAuthority(authority: string): boolean {
  if (/[\s/\\@?#%,]/.test(authority)) return false;
  try {
    const url = new URL(`http://${authority}`);
    if (url.host !== authority || !url.port || Number(url.port) < 1) return false;
    if (["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) return true;
    const octets = url.hostname.split(".").map(Number);
    return octets.length === 4 && octets.every((part) => Number.isInteger(part) && part >= 0 && part <= 255)
      && octets[0] === 100 && octets[1] >= 64 && octets[1] <= 127;
  } catch { return false; }
}
/** Browser access is provided by the explicit Tailscale/loopback listener, with
 * no dashboard login. Upstream role credentials remain server-only. */
export function validateViewerRequest(request: Request, env: ViewerEnvironment = process.env): Response | null {
  if (env.MESHMIND_UI_MODE !== "viewer") return viewerFailure(404);
  if (request.method !== "GET") return viewerFailure(405);
  const authority = env.MESHMIND_VIEWER_HOST;
  if (!authority || !validViewerAuthority(authority) || !validToken(env.MESHMIND_VIEWER_HYDRO_TOKEN) || !validToken(env.MESHMIND_VIEWER_FLOOD_TOKEN)
    || env.MESHMIND_VIEWER_HYDRO_TOKEN === env.MESHMIND_VIEWER_FLOOD_TOKEN) return viewerFailure(503);
  if (request.headers.get("host") !== authority || request.headers.get("sec-fetch-site") === "cross-site") return viewerFailure(403);
  return null;
}

/** Choose the fixed backend token by endpoint, never by browser credentials. */
export function authorizeViewer(request: Request, role: WorkerId, env: ViewerEnvironment = process.env): ViewerIdentity | Response {
  const denied = validateViewerRequest(request, env);
  if (denied) return denied;
  if (role !== "hydro" && role !== "flood") return viewerFailure(404);
  return { role, token: (role === "hydro" ? env.MESHMIND_VIEWER_HYDRO_TOKEN : env.MESHMIND_VIEWER_FLOOD_TOKEN)! };
}

/** Entire viewer listener allowlist, including framework assets and RSC requests. */
export function guardViewerSurface(request: Request, env: ViewerEnvironment = process.env): Response | null {
  if (env.MESHMIND_UI_MODE !== "viewer") return null;
  const denied = validateViewerRequest(request, env);
  if (denied) return denied;
  const url = new URL(request.url); const path = url.pathname;
  const viewerPage = path === "/viewer/hydro" || path === "/viewer/flood";
  const viewerApi = path === "/api/viewer/hydro" || path === "/api/viewer/flood";
  // Next emits dynamic-segment bundle paths such as app/viewer/%5Brole%5D/.
  // Decode only bracket escapes; encoded separators/dots and all other percent
  // sequences remain disallowed instead of broadly decoding the asset path.
  const assetPath = path.replace(/%5b/gi, "[").replace(/%5d/gi, "]");
  const asset = /^\/_next\/static\/[A-Za-z0-9_./\[\]-]+$/.test(assetPath) && !assetPath.includes("..");
  if (!(viewerPage || viewerApi || asset || path === "/icon.svg")) return viewerFailure(403);
  // Next's internal RSC query is required for rendering, but no arbitrary query
  // parameters or destination/session selectors are accepted by viewer endpoints.
  if (viewerApi && url.search || viewerPage && [...url.searchParams.keys()].some((key) => key !== "_rsc")) return viewerFailure(403);
  return null;
}
