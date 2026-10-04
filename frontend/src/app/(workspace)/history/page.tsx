import { HistoryView } from "@/components/meshmind/history-view";
export const metadata = { title: "History · Amalga" };
export default async function Page({searchParams}:{searchParams:Promise<{search?:string}>}) { const query = await searchParams; return <HistoryView search={query.search === "1"}/>; }
