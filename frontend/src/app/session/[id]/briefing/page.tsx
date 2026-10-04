import { AppShell } from "@/components/meshmind/session-sidebar";
import { BriefingView } from "@/components/meshmind/briefing-view";
export default async function Page({params}:{params:Promise<{id:string}>}) { const {id} = await params; return <AppShell><BriefingView key={id} id={id}/></AppShell>; }
