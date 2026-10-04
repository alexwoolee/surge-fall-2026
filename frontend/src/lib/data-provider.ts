import { mockProvider } from "./mock-provider";
import type { AnalysisState, DemoScenario, SessionSummary, WorkerId } from "./types";

/** The UI depends on this boundary. A future API adapter maps real contracts here. */
export interface MeshMindDataProvider {
  startAnalysis(prompt: string, scenario?: DemoScenario): Promise<string>;
  getAnalysis(id: string): Promise<AnalysisState | null>;
  listSessions(): Promise<SessionSummary[]>;
  retryWorker(id: string, worker: WorkerId): Promise<void>;
  resetDemo(): Promise<void>;
}

/** Explicit demo selection; never silently substitutes for a failed real API. */
export const dataProvider: MeshMindDataProvider = mockProvider;
