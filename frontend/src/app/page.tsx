import { AppShell } from "@/components/meshmind/session-sidebar";
import { HomeView } from "@/components/meshmind/home-view";
export default async function Page({searchParams}:{searchParams:Promise<{new?:string}>}) {
  const query = await searchParams;
  return <AppShell><HomeView key={query.new ?? "home"}/></AppShell>;
}
