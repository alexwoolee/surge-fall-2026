import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { authorizeViewer } from "@/lib/viewer-auth";
import { isWorkerId } from "@/lib/workers";
import { WorkerFollower } from "@/components/meshmind/worker-follower";
export const dynamic = "force-dynamic";
export const metadata = { title: "Worker viewer · Amalga" };
export default async function Page({ params }: { params: Promise<{ role: string }> }) {
  const { role } = await params;
  if (!isWorkerId(role)) notFound();
  // Repeat the listener/Host/method boundary independently of Proxy.
  const request = new Request(`http://127.0.0.1/viewer/${role}`, { headers: await headers() });
  if (authorizeViewer(request, role) instanceof Response) notFound();
  return <WorkerFollower key={role} role={role}/>;
}
