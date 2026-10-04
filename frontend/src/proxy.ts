import { NextResponse, type NextRequest } from "next/server";
import { guardViewerSurface, viewerHeaders } from "@/lib/viewer-auth";

export function proxy(request: NextRequest) {
  const denied = guardViewerSurface(request);
  if (denied) return denied;
  const response = NextResponse.next();
  if (process.env.MESHMIND_UI_MODE === "viewer") for (const [name, value] of Object.entries(viewerHeaders)) response.headers.set(name, value);
  return response;
}
