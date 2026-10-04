/** Frontend view models only; these are not backend/Pydantic contracts. */
export type StepState = "pending" | "active" | "complete" | "failed";
export type AgentAvailability = "ready" | "active" | "down" | "failed" | "unknown" | "complete";
export type EnvironmentalWorkerId = "hydro" | "flood";
export type WorkerId = EnvironmentalWorkerId | "dam";
export type InvestigationWorkers = Record<EnvironmentalWorkerId, WorkerStatus> & { dam?: WorkerStatus };
export type DemoScenario = "happy" | "partial" | "validation-failed" | "failed";
export type AnalysisStatus = "running" | "briefing-ready" | "partial" | "checks-failed" | "failed";
export type AnalysisPhase = "dispatched" | "processing" | "validating" | "reviewing" | "complete";

export interface WorkerStep {
  id: string;
  label: string;
  state: StepState;
  detail?: string;
}

export interface WorkerStatus {
  id: WorkerId;
  name: string;
  location: string;
  status: AgentAvailability;
  steps: WorkerStep[];
  summary: string;
  resources: string[];
  returned: boolean;
  validated: boolean;
}

export interface ActivityGroup {
  id: string;
  name: string;
  location: string;
  status: AgentAvailability;
  events: string[];
}

export interface ReviewCondition {
  id: string;
  condition: string;
  observed: string;
  configured: string;
  status: "triggered" | "not-triggered" | "not-assessable";
}

export interface ValidationFailure {
  title: string;
  detail: string;
}

export interface BriefingSection {
  id: string;
  title: string;
  paragraphs: string[];
}

export interface RiskAssessment {
  level: "unknown" | "low" | "moderate" | "high" | "critical";
  score: number | null;
  confidenceLevel: "low" | "moderate" | "high";
  confidenceScore: number;
  alert: boolean;
  title: string;
  summary: string;
  basis: string;
  limitations: string[];
}

export interface BriefingViewModel {
  title: string;
  originalRequest: string;
  studyArea: string;
  requestedWindow: string;
  actualCoverage: string;
  partial: boolean;
  sections: BriefingSection[];
  metrics: { label: string; value: string }[];
  reviewConditions: ReviewCondition[];
  sourceProvenance: { dataset: string; access: string; resources: string; coverage: string }[];
  processingProvenance: { investigation: string; location: string; method: string; duration: string }[];
  limitations: string[];
  disclaimer: string;
  demoNotice: string;
  executionNotice?: string;
  risk?: RiskAssessment | null;
}

export interface SessionSummary {
  id: string;
  title: string;
  createdAt: string;
  status: AnalysisStatus;
  description: string;
}

export interface AnalysisState extends SessionSummary {
  prompt: string;
  phase: AnalysisPhase;
  studyArea: string;
  requestedWindow: string;
  actualCoverage: string;
  control: AgentAvailability;
  workers: InvestigationWorkers;
  activities: ActivityGroup[];
  reviewConditions: ReviewCondition[];
  validationFailures: ValidationFailure[];
  briefing: BriefingViewModel | null;
  isDemo: boolean;
  executionMode?: "execute" | "review";
  executionNotice?: string;
  risk?: RiskAssessment | null;
  retryableWorkers?: WorkerId[];
  retrying: boolean;
}

export interface ControlConfig {
  mode: "execute" | "review";
  case: { case_id: string; name: string; bbox: Record<string, number>; requested_window: { start: string; end: string } };
  canStart: boolean;
  notice: string;
  routingMode?: "prompt";
  examples?: string[];
  availableWorkers?: WorkerId[];
}

export interface WorkerViewerSnapshot {
  session: null | { id: string; title: string; createdAt: string; executionNotice: string; status: AnalysisStatus };
  worker: WorkerStatus | null;
  observedAt: string | null;
  events: { id: string; observedAt: string; label: string }[];
}
