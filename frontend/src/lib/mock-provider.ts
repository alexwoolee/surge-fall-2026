import type { MeshMindDataProvider } from "./data-provider";
import {
  AGENTS, createDemoRecords, createMockBriefing, DEMO_AREA, DEMO_COVERAGE,
  DEMO_SCENARIOS, DEMO_TIMING, DEMO_WINDOW, demoReviewConditions, PARTIAL_COVERAGE,
  VALIDATION_FAILURES, WORKER_EVENTS, WORKER_STEPS,
} from "./mock-data";
import type { MockRecord } from "./mock-data";
import type { ActivityGroup, AnalysisPhase, AnalysisState, AnalysisStatus, SessionSummary, EnvironmentalWorkerId, WorkerStatus, WorkerStep } from "./types";

export interface DemoStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface MockProviderOptions {
  /** Injectable clock permits deterministic tests without timers or waiting. */
  now?: () => number;
  /** Omit for browser localStorage. Pass null for a memory-only provider. */
  storage?: DemoStorage | null;
  seed?: boolean;
}

export const DEMO_STORAGE_KEY = "meshmind.frontend-demo.v1";

function browserStorage(): DemoStorage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function validRecord(value: unknown): value is MockRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<MockRecord>;
  return typeof record.id === "string" && record.id.length > 0
    && typeof record.title === "string" && typeof record.prompt === "string"
    && typeof record.area === "string"
    && typeof record.createdAt === "number" && Number.isFinite(new Date(record.createdAt).getTime())
    && typeof record.startedAt === "number" && Number.isFinite(new Date(record.startedAt).getTime())
    && DEMO_SCENARIOS.some((scenario) => scenario.id === record.scenario)
    && (record.frozenElapsedMs === undefined || (typeof record.frozenElapsedMs === "number" && Number.isFinite(record.frozenElapsedMs) && record.frozenElapsedMs >= 0))
    && (record.retryStartedAt === undefined || (typeof record.retryStartedAt === "number" && Number.isFinite(new Date(record.retryStartedAt).getTime())));
}

function elapsedFor(record: MockRecord, now: number): number {
  if (record.retryStartedAt !== undefined) return Math.max(0, now - record.retryStartedAt);
  return record.frozenElapsedMs ?? Math.max(0, now - record.startedAt);
}

function workerState(id: EnvironmentalWorkerId, elapsed: number, flags: { down: boolean; failed: boolean; invalid: boolean; retry: boolean }): WorkerStatus {
  const agent = AGENTS[id];
  const completedAt = id === "hydro" ? DEMO_TIMING.hydroComplete : DEMO_TIMING.floodComplete;
  const complete = !flags.failed && !(id === "flood" && flags.down) && ((id === "hydro" && flags.retry) || elapsed >= completedAt);
  const down = id === "flood" && flags.down;
  const invalid = id === "flood" && flags.invalid;
  const status = flags.failed || invalid ? "failed" : down ? "down" : complete ? "ready" : "active";
  const steps: WorkerStep[] = WORKER_STEPS[id].map((step, index, all) => {
    if (flags.failed) return { id: step.id, label: step.label, state: index === 0 ? "failed" as const : "pending" as const, detail: index === 0 ? "Dispatch could not be completed" : "Not reached" };
    if (down) {
      const failedIndex = all.findIndex((item) => item.id === "sar");
      return { id: step.id, label: step.label, state: index < failedIndex ? "complete" as const : index === failedIndex ? "failed" as const : "pending" as const, detail: index === failedIndex ? "Connection lost" : index > failedIndex ? "Not reached" : undefined };
    }
    const next = all[index + 1]?.at ?? completedAt;
    return { id: step.id, label: step.label, state: complete || elapsed >= next ? "complete" as const : elapsed >= step.at ? "active" as const : "pending" as const };
  });
  if (invalid) steps.push({ id: "validation", label: "Control validation", state: "failed", detail: "Returned evidence failed coverage and freshness checks" });
  return {
    id, name: agent.name, location: agent.location, status, steps,
    summary: flags.failed ? "The investigation could not be dispatched."
      : down ? "Worker became unreachable during processing."
      : invalid ? "Result returned but did not pass validation."
      : complete ? "Result returned to Control."
      : `Executing tools on ${agent.location}`,
    resources: [...agent.resources], returned: complete,
    validated: complete && !invalid && ((id === "hydro" && flags.retry) || elapsed >= DEMO_TIMING.validating),
  };
}

function materialize(record: MockRecord, now: number): AnalysisState {
  const elapsed = elapsedFor(record, now);
  const retry = record.retryStartedAt !== undefined;
  const down = record.scenario === "partial" && !retry && elapsed >= DEMO_TIMING.floodDown;
  const failed = record.scenario === "failed" && elapsed >= DEMO_TIMING.dispatchFailed;
  const invalid = record.scenario === "validation-failed" && elapsed >= DEMO_TIMING.validating;
  const terminal = elapsed >= DEMO_TIMING.ready;
  const status: AnalysisStatus = failed ? "failed" : invalid ? "checks-failed" : terminal ? down ? "partial" : "briefing-ready" : "running";
  const phase: AnalysisPhase = status !== "running" ? "complete" : elapsed >= DEMO_TIMING.reviewing ? "reviewing" : elapsed >= DEMO_TIMING.validating ? "validating" : elapsed >= DEMO_TIMING.initial ? "processing" : "dispatched";
  const control = failed || invalid ? "failed" as const : status === "running" ? "active" as const : "ready" as const;
  const workers = {
    hydro: workerState("hydro", elapsed, { down, failed, invalid, retry }),
    flood: workerState("flood", elapsed, { down, failed, invalid, retry }),
  };
  const activities: ActivityGroup[] = [{
    id: "dispatch", name: AGENTS.control.name, location: AGENTS.control.location, status: failed ? "failed" : "ready",
    events: retry ? ["Surface Water & Terrain retry accepted.", "The validated hydrometeorology result has been retained.", "Only the missing investigation was dispatched again."]
      : failed ? ["Request accepted.", "The simulated dispatch could not reach either specialist. No evidence was returned."]
      : ["Request accepted. Demo study area and time window selected.", "Two specialist investigations dispatched concurrently in this simulation."],
  }];
  for (const id of ["hydro", "flood"] as const) {
    const worker = workers[id];
    let events = WORKER_EVENTS[id].filter((event) => event.at <= (id === "hydro" && retry ? DEMO_TIMING.hydroComplete : elapsed)).map((event) => event.text);
    if (failed) events = ["The task could not be received. No evidence was returned."];
    if (id === "flood" && down) events = [...WORKER_EVENTS.flood.filter((event) => event.at < DEMO_TIMING.floodDown).map((event) => event.text), "Worker became unreachable during processing. No result returned."];
    if (id === "hydro" && retry) events = ["Previously completed hydrometeorology evidence retained.", "No additional hydrometeorology processing was requested."];
    activities.push({ id, name: worker.name, location: worker.location, status: worker.status, events });
  }
  if (!failed && (elapsed >= DEMO_TIMING.hydroComplete || retry)) {
    const events = [workers.hydro.validated ? "Hydrometeorology result received and validated. Evidence retained." : "Hydrometeorology result received. Waiting for the independent surface-water and terrain investigation."];
    if (down) events.push("Surface-water and terrain result did not arrive. Independent completed evidence is preserved.");
    else if (workers.flood.returned) events.push("Surface-water and terrain result received.");
    if (invalid) events.push("Surface-water validation failed: coverage and freshness. Rejected evidence was not used; no combined briefing was prepared.");
    else if (elapsed >= DEMO_TIMING.validating) events.push(down ? "The available hydrometeorology evidence passed validation." : "Both returned results passed the configured validation checks.");
    if (!invalid && elapsed >= DEMO_TIMING.reviewing) events.push(down ? "Review conditions evaluated on available evidence. Missing-evidence conditions are not assessable." : "Configured review conditions evaluated. Analyst review recommended.");
    if (terminal && !invalid) events.push(down ? "Partial briefing prepared with retained evidence and explicit gaps." : "Combined environmental briefing prepared.");
    activities.push({ id: "validation", name: AGENTS.control.name, location: AGENTS.control.location, status: control, events });
  }
  const briefing = status === "briefing-ready" || status === "partial" ? createMockBriefing(record, status === "partial") : null;
  return {
    id: record.id, title: record.title, prompt: record.prompt, createdAt: new Date(record.createdAt).toISOString(),
    status, phase, description: "Hydrometeorology · Surface Water & Terrain", studyArea: record.area,
    requestedWindow: DEMO_WINDOW, actualCoverage: down ? PARTIAL_COVERAGE : DEMO_COVERAGE,
    control, workers, activities,
    reviewConditions: !invalid && !failed && elapsed >= DEMO_TIMING.reviewing ? demoReviewConditions(down) : [],
    validationFailures: invalid ? VALIDATION_FAILURES.map((failure) => ({ ...failure })) : [],
    briefing, isDemo: true, retrying: retry && status === "running",
  };
}

/** Deterministic local demo; computes state on reads, without background timers. */
export function createMockProvider(options: MockProviderOptions = {}): MeshMindDataProvider {
  const now = options.now ?? Date.now;
  let memory: MockRecord[] | null = null;
  // If a storage write fails, retain this provider's state instead of reloading an
  // older persisted snapshot on the next poll.
  let storageFailed = false;
  const storage = () => storageFailed ? null : options.storage === undefined ? browserStorage() : options.storage;
  const save = (records: MockRecord[]) => {
    memory = records;
    try {
      storage()?.setItem(DEMO_STORAGE_KEY, JSON.stringify({ version: 1, records }));
    } catch {
      storageFailed = true;
    }
  };
  const load = (): MockRecord[] => {
    try {
      const raw = storage()?.getItem(DEMO_STORAGE_KEY);
      if (raw) {
        const parsed: unknown = JSON.parse(raw);
        if (parsed && typeof parsed === "object" && "version" in parsed && parsed.version === 1 && "records" in parsed && Array.isArray(parsed.records) && parsed.records.every(validRecord)) {
          memory = parsed.records;
          return memory;
        }
      }
    } catch {
      // Blocked/quota-limited storage or old/malformed data cannot break the UI.
    }
    if (memory) return memory;
    const records = options.seed === false ? [] : createDemoRecords(now());
    save(records);
    return records;
  };
  return {
    async startAnalysis(prompt, scenario = "happy") {
      const cleanPrompt = prompt.trim();
      if (!cleanPrompt) throw new Error("Enter an environmental question to start an investigation.");
      if (!DEMO_SCENARIOS.some((item) => item.id === scenario)) throw new Error("Unknown demo scenario.");
      const records = load();
      const timestamp = now();
      let suffix = records.length;
      let id = `investigation-${timestamp.toString(36)}-${suffix}`;
      while (records.some((record) => record.id === id)) id = `investigation-${timestamp.toString(36)}-${++suffix}`;
      save([{ id, title: "Flood susceptibility, Abbotsford / Sumas Prairie", prompt: cleanPrompt, area: DEMO_AREA, scenario, createdAt: timestamp, startedAt: timestamp }, ...records]);
      return id;
    },
    async getAnalysis(id) {
      const record = load().find((item) => item.id === id);
      return record ? materialize(record, now()) : null;
    },
    async listSessions() {
      const timestamp = now();
      return load().slice().sort((a, b) => b.createdAt - a.createdAt).map((record): SessionSummary => {
        const { id, title, createdAt, status, description } = materialize(record, timestamp);
        return { id, title, createdAt, status, description };
      });
    },
    async retryWorker(id, worker) {
      if (worker !== "flood") throw new Error("This demo retries only the missing Surface Water & Terrain investigation.");
      const records = load();
      const record = records.find((item) => item.id === id);
      if (!record) throw new Error("Investigation not found.");
      const timestamp = now();
      if (materialize(record, timestamp).status !== "partial") throw new Error("Only a partial investigation with missing surface-water evidence can be retried.");
      save(records.map((item) => item.id === id ? { ...item, retryStartedAt: timestamp } : item));
    },
    async resetDemo() {
      save(options.seed === false ? [] : createDemoRecords(now()));
    },
  };
}

export const mockProvider = createMockProvider();
