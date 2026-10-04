import type { MeshMindDataProvider } from "./data-provider";
import type { AnalysisState, ControlConfig, SessionSummary } from "./types";
import { matchingRisk, optionalRisk } from "./risk";
import { isWorkerId } from "./workers";

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ROOT = "/api/control";
const PENDING_KEY = "meshmind.control.pending.v1";
const statuses = ["running", "briefing-ready", "partial", "checks-failed", "failed"];
const availability = ["unknown", "complete", "ready", "active", "down", "failed"];
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((entry) => typeof entry === "string");
const stringKeys = (value: unknown, keys: string[]) => object(value) && keys.every((key) => typeof value[key] === "string");
function summary(value: unknown): value is SessionSummary {
  return object(value) && stringKeys(value, ["id", "title", "description", "createdAt"])
    && UUID.test(String(value.id)) && Number.isFinite(Date.parse(String(value.createdAt))) && statuses.includes(String(value.status));
}
function conditions(value: unknown): boolean {
  return Array.isArray(value) && value.every((entry) => stringKeys(entry, ["id", "condition", "observed", "configured", "status"])
    && ["triggered", "not-triggered", "not-assessable"].includes(entry.status));
}
function analysis(value: unknown): value is AnalysisState {
  if (!object(value) || !summary(value) || value.isDemo !== false
    || !["execute", "review"].includes(String(value.executionMode))
    || !stringKeys(value, ["prompt", "studyArea", "requestedWindow", "actualCoverage", "executionNotice"])
    || !["dispatched", "processing", "validating", "reviewing", "complete"].includes(String(value.phase))
    || !availability.includes(String(value.control)) || typeof value.retrying !== "boolean"
    || !object(value.workers) || !Array.isArray(value.retryableWorkers)
    || !optionalRisk(value.risk)
    || !Object.keys(value.workers).every(isWorkerId)
    || !Object.hasOwn(value.workers, "hydro") || !Object.hasOwn(value.workers, "flood")
    || new Set(value.retryableWorkers).size !== value.retryableWorkers.length
    || !value.retryableWorkers.every((worker) => isWorkerId(worker) && Object.hasOwn(value.workers as object, worker))) return false;
  for (const id of Object.keys(value.workers)) {
    const worker = value.workers[id];
    if (!object(worker) || worker.id !== id || !stringKeys(worker, ["name", "location", "summary"])
      || !availability.includes(String(worker.status)) || !strings(worker.resources)
      || typeof worker.returned !== "boolean" || typeof worker.validated !== "boolean"
      || !Array.isArray(worker.steps) || !worker.steps.every((step) => stringKeys(step, ["id", "label", "state"])
        && ["pending", "active", "complete", "failed"].includes(step.state)
        && (step.detail === undefined || typeof step.detail === "string"))) return false;
  }
  if (!Array.isArray(value.activities) || !value.activities.every((entry) => stringKeys(entry, ["id", "name", "location"])
    && availability.includes(String(entry.status)) && strings(entry.events))
    || !conditions(value.reviewConditions) || !Array.isArray(value.validationFailures)
    || !value.validationFailures.every((entry) => stringKeys(entry, ["title", "detail"]))) return false;
  const b = value.briefing;
  return b === null || (object(b) && stringKeys(b, ["title", "originalRequest", "studyArea", "requestedWindow", "actualCoverage", "disclaimer", "demoNotice"])
    && typeof b.partial === "boolean" && (b.executionNotice === undefined || typeof b.executionNotice === "string")
    && optionalRisk(b.risk) && matchingRisk(value.risk, b.risk)
    && strings(b.limitations) && conditions(b.reviewConditions)
    && Array.isArray(b.sections) && b.sections.every((entry) => stringKeys(entry, ["id", "title"]) && strings(entry.paragraphs))
    && Array.isArray(b.metrics) && b.metrics.every((entry) => stringKeys(entry, ["label", "value"]))
    && Array.isArray(b.sourceProvenance) && b.sourceProvenance.every((entry) => stringKeys(entry, ["dataset", "access", "resources", "coverage"]))
    && Array.isArray(b.processingProvenance) && b.processingProvenance.every((entry) => stringKeys(entry, ["investigation", "location", "method", "duration"])));
}

export class ControlApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ControlApiError"; }
}
function errorMessage(status: number): string {
  if (status === 409) return "Control could not accept this request in its current state. Refresh this investigation and check History before trying again.";
  if (status === 400 || status === 422) return "The request was not accepted. Include a supported study area and explicit dates, and check the investigation guidance.";
  if (status === 401 || status === 403 || status === 503) return "Control is unavailable or is not configured for this action. Ask the operator to check the local setup.";
  return "Control could not complete this request. Check History before trying again.";
}
interface PendingStorage { getItem(key: string): string | null; setItem(key: string, value: string): void; }
interface ApiOptions { fetcher?: typeof fetch; uuid?: () => string; storage?: PendingStorage | null; }
export function createApiProvider({ fetcher = (...args) => fetch(...args), uuid = () => crypto.randomUUID(), storage }: ApiOptions = {}): MeshMindDataProvider {
  const pending = new Map<string, string>();
  function getStorage() { try { return storage === undefined ? (typeof window === "undefined" ? null : window.sessionStorage) : storage; } catch { return null; } }
  function savePending() { try { getStorage()?.setItem(PENDING_KEY, JSON.stringify([...pending].slice(-20))); } catch { /* Memory retains uncertain actions if browser storage is unavailable. */ } }
  function requestId(key: string): string {
    if (!pending.size) {
      try {
        const data: unknown = JSON.parse(getStorage()?.getItem(PENDING_KEY) || "[]");
        if (Array.isArray(data) && data.length <= 20) for (const entry of data) {
          if (Array.isArray(entry) && entry.length === 2 && typeof entry[0] === "string" && entry[0].length <= 4100 && typeof entry[1] === "string" && UUID.test(entry[1])) pending.set(entry[0], entry[1]);
        }
      } catch { /* Corrupt storage is ignored. */ }
    }
    const id = pending.get(key) || uuid(); pending.set(key, id); savePending(); return id;
  }
  async function request(path: string, signal?: AbortSignal, body?: object): Promise<unknown> {
    let response: Response;
    try {
      response = await fetcher(`${ROOT}${path}`, { method: body ? "POST" : "GET", cache: "no-store", credentials: "same-origin", redirect: "error", signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000), headers: body ? { "Content-Type": "application/json" } : {}, ...(body ? { body: JSON.stringify(body) } : {}) });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new ControlApiError(0, body ? "The response was interrupted; the request may have been accepted. Check History, or submit the same request to safely check its outcome." : "Control could not be reached. The last received evidence has been retained.");
    }
    if (!response.ok) throw new ControlApiError(response.status, errorMessage(response.status));
    try { return await response.json(); } catch { throw new ControlApiError(0, "Control returned an unreadable response. Check History before trying again."); }
  }
  function requireId(id: string) { if (!UUID.test(id)) throw new ControlApiError(400, "This investigation ID is not valid."); }
  async function mutate(path: string, key: string, body: object): Promise<string> {
    const id = requestId(key);
    try {
      const response = await request(path, undefined, { ...body, requestId: id });
      if (!object(response) || typeof response.id !== "string" || !UUID.test(response.id)) throw new ControlApiError(0, "Control returned an unreadable response. Check History before trying again.");
      pending.delete(key); savePending(); return response.id;
    } catch (error) {
      // An uncertain transport/server failure keeps the same idempotency key. No automatic replay.
      if (error instanceof ControlApiError && error.status >= 400 && error.status < 500) { pending.delete(key); savePending(); }
      throw error;
    }
  }
  return {
    async getConfig(signal) {
      const result = await request("/config", signal);
      if (!object(result) || !["execute", "review"].includes(String(result.mode)) || typeof result.canStart !== "boolean" || typeof result.notice !== "string" || !object(result.case) || !stringKeys(result.case, ["case_id", "name"]) || !object(result.case.bbox) || !stringKeys(result.case.requested_window, ["start", "end"])) throw new ControlApiError(502, "Control configuration could not be read.");
      if (result.routingMode !== undefined && result.routingMode !== "prompt"
        || result.examples !== undefined && (!strings(result.examples) || result.examples.length > 10 || result.examples.some((example) => !example.trim() || example.length > 4000))
        || result.availableWorkers !== undefined && (!Array.isArray(result.availableWorkers) || !result.availableWorkers.every(isWorkerId) || new Set(result.availableWorkers).size !== result.availableWorkers.length || !result.availableWorkers.includes("hydro") || !result.availableWorkers.includes("flood"))
        || result.routingMode === "prompt" && (!strings(result.examples) || !Array.isArray(result.availableWorkers))) throw new ControlApiError(502, "Control configuration could not be read.");
      return result as unknown as ControlConfig;
    },
    async startAnalysis(prompt) {
      if (!prompt.trim() || prompt.length > 4000 || new TextEncoder().encode(prompt.trim()).length > 4096) throw new ControlApiError(400, "Enter a request of up to 4,000 characters and 4,096 UTF-8 bytes.");
      return mutate("/sessions", `start:${prompt.trim()}`, { prompt: prompt.trim() });
    },
    async getAnalysis(id, signal) {
      requireId(id);
      let result: unknown;
      try { result = await request(`/sessions/${id}`, signal); } catch (error) { if (error instanceof ControlApiError && error.status === 404) return null; throw error; }
      if (!analysis(result) || result.id !== id) throw new ControlApiError(502, "Control returned an invalid investigation response.");
      return result;
    },
    async listSessions(signal) {
      const result = await request("/sessions", signal);
      if (!object(result) || !Array.isArray(result.sessions) || !result.sessions.every(summary)) throw new ControlApiError(502, "Control returned an invalid history response.");
      return result.sessions;
    },
    async retryWorker(id, worker) {
      requireId(id);
      if (!isWorkerId(worker)) throw new ControlApiError(400, "Unknown investigation.");
      await mutate(`/sessions/${id}/retry`, `retry:${id}:${worker}`, { worker });
    },
    async resetDemo() { throw new Error("Demo reset is unavailable in Control mode."); },
  };
}
export const apiProvider = createApiProvider();
export function briefingDownload(id: string) { if (!UUID.test(id)) throw new Error("Invalid investigation ID"); return { href: `${ROOT}/sessions/${id}/briefing`, filename: `amalga-${id}-briefing.html` }; }
