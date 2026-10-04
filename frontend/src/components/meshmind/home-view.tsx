"use client";
import { useControlConfig } from "@/hooks/use-meshmind";
import { isDemoMode } from "@/lib/data-provider";
import { configuredWorkers, WORKERS } from "@/lib/workers";
import { Composer } from "./composer";
import { TeamRoster } from "./agent-status";

export function HomeView() {
  const { config } = useControlConfig();
  const agents = [
    { id: "control", name: "Control", location: "Coordinator" },
    ...configuredWorkers(config).map((id) => ({ id, name: WORKERS[id].name, location: WORKERS[id].location })),
  ];
  return <div className="home-view">
    <h1 className="home-title">What should we analyze?</h1>
    <Composer autoFocus />
    <TeamRoster agents={agents.map((agent) => ({ ...agent, status: isDemoMode ? "ready" : "unknown" }))} />
  </div>;
}
