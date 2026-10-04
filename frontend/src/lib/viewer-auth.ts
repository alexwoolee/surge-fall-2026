/** Node-only viewer access boundary; never import this module from client code. */
import { timingSafeEqual } from "node:crypto";
import type { WorkerId } from "./types";

export type ViewerEnvironment = Record<string, string | undefined>;
export type ViewerIdentity = { role: WorkerId; token: string };
export const viewerHeaders = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY" };
export const viewerFailure = (status: number) => new Response("Worker viewer is unavailable.", { status, headers: { ...viewerHeaders, ...(status === 401 ? { "WWW-Authenticate": 'Basic realm="MeshMind worker viewer", charset="UTF-8"' } : {}) } });
const validToken = (token: string | undefined): token is string => !!token && token.length >= 32 && token.length <= 256 && /^[A-Za-z0-9_-]+$/.test(token);
function equal(left: string, right: string): boolean {
  const a = Buffer.from(left); const b = Buffer.from(right);
  return a.byteLength === b.byteLength && timingSafeEqual(a, b);
}
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
export function authorizeViewer(request: Request, expectedRole?: WorkerId, env: ViewerEnvironment = process.env): ViewerIdentity | Response {
  if (env.MESHMIND_UI_MODE !== "viewer") return viewerFailure(404);
  if (request.method !== "GET") return viewerFailure(405);
  const authority = env.MESHMIND_VIEWER_HOST;
  if (!authority || !validViewerAuthority(authority) || !validToken(env.MESHMIND_VIEWER_HYDRO_TOKEN) || !validToken(env.MESHMIND_VIEWER_FLOOD_TOKEN)
    || equal(env.MESHMIND_VIEWER_HYDRO_TOKEN, env.MESHMIND_VIEWER_FLOOD_TOKEN)) return viewerFailure(503);
  if (request.headers.get("host") !== authority || request.headers.get("sec-fetch-site") === "cross-site") return viewerFailure(403);
  const encoded = request.headers.get("authorization");
  if (!encoded || encoded.length > 600 || !/^Basic [A-Za-z0-9+/]+={0,2}$/i.test(encoded)) return viewerFailure(401);
  let credentials: string;
  try { credentials = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.from(encoded.slice(6), "base64")); } catch { return viewerFailure(401); }
  const split = credentials.indexOf(":"); const role = credentials.slice(0, split); const supplied = credentials.slice(split + 1);
  if (split < 0 || (role !== "hydro" && role !== "flood")) return viewerFailure(401);
  const token = role === "hydro" ? env.MESHMIND_VIEWER_HYDRO_TOKEN : env.MESHMIND_VIEWER_FLOOD_TOKEN;
  if (!equal(supplied, token)) return viewerFailure(401);
  if (expectedRole && role !== expectedRole) return viewerFailure(403);
  return { role, token };
}

/** Entire viewer listener allowlist, including framework assets and RSC requests. */
export function guardViewerSurface(request: Request, env: ViewerEnvironment = process.env): Response | null {
  if (env.MESHMIND_UI_MODE !== "viewer") return null;
  const identity = authorizeViewer(request, undefined, env);
  if (identity instanceof Response) return identity;
  const url = new URL(request.url); const path = url.pathname;
  const ownPage = path === `/viewer/${identity.role}`;
  const ownApi = path === `/api/viewer/${identity.role}`;
  // Next emits dynamic-segment bundle paths such as app/viewer/%5Brole%5D/.
  // Decode only bracket escapes; encoded separators/dots and all other percent
  // sequences remain disallowed instead of broadly decoding the asset path.
  const assetPath = path.replace(/%5b/gi, "[").replace(/%5d/gi, "]");
  const asset = /^\/_next\/static\/[A-Za-z0-9_./\[\]-]+$/.test(assetPath) && !assetPath.includes("..");
  if (!(ownPage || ownApi || asset || path === "/icon.svg")) return viewerFailure(403);
  // Next's internal RSC query is required for rendering, but no arbitrary query
  // parameters or destination/session selectors are accepted by viewer endpoints.
  if (ownApi && url.search || ownPage && [...url.searchParams.keys()].some((key) => key !== "_rsc")) return viewerFailure(403);
  return null;
}
