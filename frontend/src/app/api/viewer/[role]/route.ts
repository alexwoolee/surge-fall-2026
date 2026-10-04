import { proxyWorkerViewer } from "@/lib/viewer-proxy";
import { isWorkerId } from "@/lib/workers";
import { viewerFailure } from "@/lib/viewer-auth";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request, context: { params: Promise<{ role: string }> }) {
  const { role } = await context.params;
  if (!isWorkerId(role)) return viewerFailure(404);
  return proxyWorkerViewer(request, role);
}
