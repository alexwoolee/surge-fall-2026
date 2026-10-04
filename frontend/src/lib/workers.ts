import type { ControlConfig, WorkerId } from "./types";

export const WORKERS = {
  hydro: { name: "Hydrometeorology", location: "Hydro worker", mark: "H" },
  flood: { name: "Surface Water & Terrain", location: "Flood worker", mark: "F" },
  dam: { name: "Dam Condition", location: "Owner records · Toddbrook only", mark: "D" },
} as const;

export function isWorkerId(value: unknown): value is WorkerId { return value === "hydro" || value === "flood" || value === "dam"; }
export function configuredWorkers(config: ControlConfig | null): WorkerId[] {
  return config?.availableWorkers?.includes("dam") ? ["hydro", "flood", "dam"] : ["hydro", "flood"];
}
