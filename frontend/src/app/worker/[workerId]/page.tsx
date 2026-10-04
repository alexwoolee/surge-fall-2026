import { isWorkerId } from "@/lib/workers";
import { notFound } from "next/navigation";
import { WorkerView } from "@/components/meshmind/worker-view";
export const metadata = { title: "Worker activity · Amalga" };
export default async function Page({params,searchParams}:{params:Promise<{workerId:string}>;searchParams:Promise<{session?:string}>}) { const {workerId} = await params; const {session} = await searchParams; if(!isWorkerId(workerId)) notFound(); return <WorkerView key={`${workerId}-${session}`} workerId={workerId} sessionId={session}/>; }
