import { SessionView } from "@/components/meshmind/session-view";
export default async function Page({params}:{params:Promise<{id:string}>}) { const {id} = await params; return <SessionView key={id} id={id}/>; }
