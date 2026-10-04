import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { authorizeViewer } from "@/lib/viewer-auth";
import { WorkerFollower } from "@/components/meshmind/worker-follower";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ role: string }> }) {
  const { role } = await params;
  if (role !== "hydro" && role !== "flood") notFound();
  // Repeat role authentication at the page boundary, independently of Proxy.
  const request = new Request(`http://127.0.0.1/viewer/${role}`, { headers: await headers() });
  if (authorizeViewer(request, role) instanceof Response) notFound();
  return <WorkerFollower key={role} role={role}/>;
}
