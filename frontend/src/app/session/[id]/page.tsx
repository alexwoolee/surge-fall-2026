import { AppShell } from "@/components/meshmind/session-sidebar";
import { SessionView } from "@/components/meshmind/session-view";
export default async function Page({params}:{params:Promise<{id:string}>}) { const {id} = await params; return <AppShell><SessionView key={id} id={id}/></AppShell>; }
