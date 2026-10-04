import { proxyControl } from "@/lib/control-proxy";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function handler(request: Request, context: { params: Promise<{ path: string[] }> }) {
  return proxyControl(request, (await context.params).path);
}
export { handler as GET, handler as POST };
