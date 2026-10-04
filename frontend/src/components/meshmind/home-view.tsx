"use client";
import { isDemoMode } from "@/lib/data-provider";
import { Composer } from "./composer";
import { TeamRoster } from "./agent-status";

const AGENTS = [
  { id: "control", name: "Control", location: "Laptop 1" },
  { id: "hydro", name: "Hydrometeorology", location: "Laptop 2" },
  { id: "flood", name: "Surface Water & Terrain", location: "Laptop 3" },
];

export function HomeView() {
  return <div className="home-view">
    <h1 className="home-title">What should we analyze?</h1>
    <Composer autoFocus />
    <TeamRoster agents={AGENTS.map((agent) => ({ ...agent, status: isDemoMode ? "ready" : "unknown" }))} />
  </div>;
}
