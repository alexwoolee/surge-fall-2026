import type { WorkerId, WorkerViewerSnapshot } from "./types";
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown, max = 8192): value is string => typeof value === "string" && value.length <= max;
const date = (value: unknown) => str(value, 64) && Number.isFinite(Date.parse(value));
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).sort().join(",") === keys.sort().join(",");
const available = ["ready", "active", "down", "failed", "unknown", "complete"];
export function parseViewerSnapshot(value: unknown, role: WorkerId): WorkerViewerSnapshot {
  const invalid = () => { throw new Error("Worker viewer returned an invalid state."); };
  if (!object(value) || !exact(value, ["session", "worker", "observedAt", "events"])) return invalid();
  if (value.observedAt !== null && !date(value.observedAt)) return invalid();
  if (!Array.isArray(value.events) || value.events.length > 256 || !value.events.every((event) => object(event)
    && exact(event, ["id", "observedAt", "label"]) && str(event.id, 256) && date(event.observedAt) && str(event.label))) return invalid();
  if (new Set(value.events.map((event) => event.id)).size !== value.events.length) return invalid();
  if (value.session === null) {
    if (value.worker !== null || value.observedAt !== null || value.events.length) return invalid();
    return { session: null, worker: null, observedAt: null, events: [] };
  }
  const s = value.session; const w = value.worker;
  if (!object(s) || !exact(s, ["id", "title", "createdAt", "executionNotice", "status"])
    || !str(s.id, 36) || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(s.id)
    || !str(s.title) || !date(s.createdAt) || !str(s.executionNotice)
    || !["running", "briefing-ready", "partial", "checks-failed", "failed"].includes(String(s.status))) return invalid();
  if (!object(w) || !exact(w, ["id", "name", "location", "status", "steps", "summary", "resources", "returned", "validated"])
    || w.id !== role || !str(w.name) || !str(w.location) || !str(w.summary) || !available.includes(String(w.status))
    || typeof w.returned !== "boolean" || typeof w.validated !== "boolean"
    || !Array.isArray(w.resources) || w.resources.length > 20 || !w.resources.every((resource) => str(resource))
    || !Array.isArray(w.steps) || w.steps.length > 20 || !w.steps.every((step) => object(step)
      && exact(step, step.detail === undefined ? ["id", "label", "state"] : ["id", "label", "state", "detail"])
      && str(step.id, 256) && str(step.label) && ["pending", "active", "complete", "failed"].includes(String(step.state))
      && (step.detail === undefined || str(step.detail)))) return invalid();
  return value as unknown as WorkerViewerSnapshot;
}
