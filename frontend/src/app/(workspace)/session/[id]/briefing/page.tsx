import { BriefingView } from "@/components/meshmind/briefing-view";
export const metadata = { title: "Briefing · Amalga" };
export default async function Page({params}:{params:Promise<{id:string}>}) { const {id} = await params; return <BriefingView key={id} id={id}/>; }
