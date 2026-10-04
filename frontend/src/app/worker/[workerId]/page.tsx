import { notFound } from "next/navigation";
import { WorkerView } from "@/components/meshmind/worker-view";
export default async function Page({params,searchParams}:{params:Promise<{workerId:string}>;searchParams:Promise<{session?:string}>}) { const {workerId} = await params; const {session} = await searchParams; if(workerId!=="hydro" && workerId!=="flood") notFound(); return <WorkerView key={`${workerId}-${session}`} workerId={workerId} sessionId={session}/>; }
