import { HomeView } from "@/components/meshmind/home-view";
export const metadata = { title: "New investigation · Amalga" };
export default async function Page({searchParams}:{searchParams:Promise<{new?:string}>}) {
  const query = await searchParams;
  return <HomeView key={query.new ?? "home"}/>;
}
