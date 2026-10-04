import { mockProvider } from "./mock-provider";
import { apiProvider } from "./api-provider";
import type { AnalysisState, ControlConfig, DemoScenario, SessionSummary, WorkerId } from "./types";

export interface MeshMindDataProvider {
  startAnalysis(prompt: string, scenario?: DemoScenario): Promise<string>;
  getAnalysis(id: string, signal?: AbortSignal): Promise<AnalysisState | null>;
  listSessions(signal?: AbortSignal): Promise<SessionSummary[]>;
  getConfig?(signal?: AbortSignal): Promise<ControlConfig>;
  retryWorker(id: string, worker: WorkerId): Promise<void>;
  resetDemo(): Promise<void>;
}

/** Build-time opt-in only. Network failure never selects fixtures. */
export const isDemoMode = process.env.NEXT_PUBLIC_MESHMIND_MODE === "demo";
export const dataProvider: MeshMindDataProvider = isDemoMode ? mockProvider : apiProvider;
