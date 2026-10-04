/* Self-contained worker dashboard: no Control requests or browser credentials. */
const TASK_STATES = ["task_received", "acquiring_data", "dataset_located", "processing", "preparing_result", "complete", "partial", "failed"];
const TERMINAL = ["complete", "partial", "failed"];
const STATUS_LABELS = { idle: "Idle", active: "Active", complete: "Complete", partial: "Complete", failed: "Processing failed" };
const STAGE_LABELS = { task_received: "Task accepted", acquiring_data: "Finding and downloading input data", dataset_located: "Input data located", processing: "Processing data", preparing_result: "Preparing result", complete: "Result ready", partial: "Result ready", failed: "Processing failed" };
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const isString = (value, limit = 4096) => typeof value === "string" && value.length <= limit;
const isDate = (value) => isString(value, 64) && Number.isFinite(Date.parse(value));
const exactKeys = (value, keys) => Object.keys(value).sort().join(",") === [...keys].sort().join(",");

export function validateDashboardState(value) {
  const fail = () => { throw new Error("Worker dashboard state is invalid."); };
  if (!isObject(value) || !exactKeys(value, ["role", "name", "status", "task", "events", "notice", ...(value.role === "dam" ? ["risk"] : [])])
    || !["hydro", "flood", "dam"].includes(value.role) || !isString(value.name, 160) || !isString(value.notice)
    || !["idle", "active", ...TERMINAL].includes(value.status) || !Array.isArray(value.events) || value.events.length > 256
    || !value.events.every((event) => isObject(event) && exactKeys(event, ["state", "observedAt", "label"])
      && TASK_STATES.includes(event.state) && isDate(event.observedAt) && isString(event.label))) return fail();
  if (value.role === "dam" && value.risk !== null) {
    const risk = value.risk;
    if (!isObject(risk) || !exactKeys(risk, ["level", "score", "confidenceLevel", "confidenceScore", "alert", "asOf"])
      || !["unknown", "low", "moderate", "high", "critical"].includes(risk.level)
      || (risk.level === "unknown" ? risk.score !== null : !Number.isInteger(risk.score) || risk.score < 0 || risk.score > 100)
      || !["low", "moderate", "high"].includes(risk.confidenceLevel)
      || typeof risk.confidenceScore !== "number" || !Number.isFinite(risk.confidenceScore) || risk.confidenceScore < 0 || risk.confidenceScore > 1
      || typeof risk.alert !== "boolean" || risk.alert !== ["high", "critical"].includes(risk.level)
      || !isDate(risk.asOf) || value.status !== "complete") return fail();
  }
  if (value.task === null) {
    if (value.status !== "idle" || value.events.length) return fail();
    return value;
  }
  const task = value.task;
  if (!isObject(task) || !exactKeys(task, ["id", "state", "receivedAt", "startedAt", "completedAt", "durationSeconds"])
    || !isString(task.id, 128) || !/^[A-Za-z0-9_-]{1,128}$/.test(task.id) || !TASK_STATES.includes(task.state) || !isDate(task.receivedAt)
    || task.startedAt !== null && !isDate(task.startedAt) || task.completedAt !== null && !isDate(task.completedAt)
    || task.durationSeconds !== null && (typeof task.durationSeconds !== "number" || !Number.isFinite(task.durationSeconds) || task.durationSeconds < 0 || task.startedAt === null || task.completedAt === null)
    || value.status !== (TERMINAL.includes(task.state) ? task.state : "active")) return fail();
  return value;
}

export function formatDuration(seconds) {
  if (seconds === null) return "Available after processing ends";
  const milliseconds = seconds * 1000;
  if (milliseconds > 0 && milliseconds < 0.001) return "Less than 0.001 ms";
  const ms = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 3 }).format(milliseconds);
  return `${ms} ms${seconds >= 1 ? ` (${new Intl.NumberFormat("en-CA", { maximumFractionDigits: 3 }).format(seconds)} s)` : ""}`;
}

/** Completion describes the worker's execution, independent of data coverage. */
export function dashboardStatusLabel(snapshot) {
  return STATUS_LABELS[snapshot.status];
}

/** Only recorded stages count as observed; no clock-based progress is inferred. */
export function observedStages(snapshot) {
  if (!snapshot.task) return [];
  const observed = new Set(snapshot.events.map((event) => event.state));
  const current = snapshot.task.state;
  observed.add(current);
  return [...TASK_STATES.filter((state) => !TERMINAL.includes(state)), TERMINAL.includes(current) ? current : "complete"].map((state) => ({
    state, label: STAGE_LABELS[state],
    progress: state === current ? (current === "partial" ? "complete" : TERMINAL.includes(current) ? current : "active") : observed.has(state) ? "complete" : "pending",
  }));
}

async function readBoundedJson(response, signal) {
  if (!response.ok || response.headers.get("content-type")?.split(";")[0].trim() !== "application/json" || !response.body) throw new Error("Worker state unavailable");
  const reader = response.body.getReader(); const chunks = []; let size = 0;
  const abort = () => { void reader.cancel().catch(() => undefined); };
  signal.addEventListener("abort", abort, { once: true });
  try {
    if (signal.aborted) throw new Error("Aborted");
    while (true) {
      const { done, value } = await reader.read();
      if (signal.aborted) throw new Error("Aborted");
      if (done) break;
      size += value.byteLength;
      if (size > 512 * 1024) { await reader.cancel(); throw new Error("Worker state exceeds size limit"); }
      chunks.push(value);
    }
  } finally { signal.removeEventListener("abort", abort); reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
}

export function startDashboardPolling(options) {
  const controller = new AbortController(); let cancelTimer;
  const schedule = options.schedule || ((callback, delay) => { const timer = setTimeout(callback, delay); return () => clearTimeout(timer); });
  const fetcher = options.fetcher || fetch;
  async function read() {
    const attempt = new AbortController();
    const abort = () => attempt.abort();
    controller.signal.addEventListener("abort", abort, { once: true });
    const timeout = setTimeout(abort, 10000);
    let delay = 1000;
    try {
      const response = await fetcher("/dashboard/state", { method: "GET", credentials: "omit", cache: "no-store", redirect: "error", signal: attempt.signal });
      const snapshot = validateDashboardState(await readBoundedJson(response, attempt.signal));
      if (controller.signal.aborted) return;
      options.onState(snapshot);
    } catch {
      if (controller.signal.aborted) return;
      options.onError("Updates from this worker are unavailable. Displaying the last observed state; active animations are paused.");
      delay = 3000;
    } finally { clearTimeout(timeout); controller.signal.removeEventListener("abort", abort); }
    if (!controller.signal.aborted) cancelTimer = schedule(() => { void read(); }, delay);
  }
  void read();
  return () => { controller.abort(); if (cancelTimer) cancelTimer(); };
}

/** Resume a fresh subscription after back-forward-cache restoration. */
export function attachDashboardLifecycle(target, start, onSuspend) {
  let stop;
  const begin = () => { if (stop) stop(); stop = start(); };
  const suspend = () => { if (stop) stop(); stop = undefined; onSuspend(); };
  const resume = (event) => { if (event.persisted) begin(); };
  target.addEventListener("pagehide", suspend);
  target.addEventListener("pageshow", resume);
  begin();
  return () => { if (stop) stop(); target.removeEventListener("pagehide", suspend); target.removeEventListener("pageshow", resume); };
}

function renderDashboard(document, snapshot) {
  const setText = (id, text) => { document.getElementById(id).textContent = text; };
  const root = document.getElementById("dashboard");
  root.dataset.status = snapshot.status === "partial" ? "complete" : snapshot.status; root.dataset.stale = "false";
  document.getElementById("connection-warning").hidden = true;
  document.title = `MeshMind · ${snapshot.name}`;
  setText("role-label", snapshot.role === "hydro" ? "Hydrometeorology" : snapshot.role === "dam" ? "Reservoir Risk" : "Surface Water & Terrain");
  setText("worker-name", snapshot.name);
  setText("worker-subtitle", snapshot.status === "active" ? "Executing on this laptop" : "Hosted on this laptop");
  setText("worker-status", dashboardStatusLabel(snapshot));
  setText("worker-notice", snapshot.notice);
  const riskCard = document.getElementById("risk-card");
  if (riskCard) {
    const risk = snapshot.role === "dam" ? snapshot.risk : null;
    riskCard.hidden = !risk;
    if (risk) {
      riskCard.dataset.alert = String(risk.alert);
      setText("risk-heading", risk.alert ? "Flood risk screening alert" : "Reservoir risk screening");
      setText("risk-level", risk.level === "unknown" ? "UNKNOWN · insufficient temporal coverage" : `${risk.level.toUpperCase()} · ${risk.score}/100 screening index`);
      setText("risk-confidence", `${risk.confidenceLevel} evidence confidence · ${Math.round(risk.confidenceScore * 100)}% · as of ${risk.asOf}`);
    }
  }
  const task = snapshot.task;
  document.getElementById("task-card").hidden = !task;
  document.getElementById("events-card").hidden = !task;
  setText("waiting-note", !task ? "Waiting for a task from Control. Keep this page open; the next accepted task appears automatically." : TERMINAL.includes(task.state) ? "Most recent task finished. Waiting for the next request from Control." : "Following this worker's accepted task.");
  if (!task) return;
  const time = (value) => new Date(value).toISOString().replace("T", " ").replace("Z", " UTC");
  setText("task-heading", TERMINAL.includes(task.state) ? "Most recent investigation" : "Current investigation");
  setText("task-id", task.id);
  setText("task-received", time(task.receivedAt));
  setText("task-duration", formatDuration(task.durationSeconds));
  setText("task-summary", ["complete", "partial"].includes(task.state) ? "The worker has prepared its result. See the report for the available observations and findings." : task.state === "failed" ? "Processing failed. This dashboard does not turn missing observations into successful results." : STAGE_LABELS[task.state] + ".");
  const timeline = document.getElementById("task-timeline");
  const stepLabels = { complete: "Observed", active: "Current stage", partial: "Partial evidence", failed: "Failed", pending: "Not observed" };
  timeline.replaceChildren(...observedStages(snapshot).map((step) => {
    const item = document.createElement("li"); item.className = `timeline-step step-${step.progress}`;
    const marker = document.createElement("span"); marker.className = "step-marker"; marker.setAttribute("aria-hidden", "true"); marker.textContent = step.progress === "complete" ? "✓" : step.progress === "failed" ? "×" : step.progress === "active" ? "•" : "";
    const label = document.createElement("span"); label.className = "step-copy"; label.textContent = step.label;
    const detail = document.createElement("span"); detail.className = "step-detail"; detail.textContent = stepLabels[step.progress];
    item.append(marker, label, detail); return item;
  }));
  const events = document.getElementById("events-list");
  events.replaceChildren(...snapshot.events.map((event) => {
    const item = document.createElement("li");
    const timestamp = document.createElement("time"); timestamp.dateTime = event.observedAt; timestamp.textContent = time(event.observedAt);
    const label = document.createElement("span"); label.textContent = event.label;
    item.append(timestamp, label); return item;
  }));
  document.getElementById("events-empty").hidden = snapshot.events.length > 0;
}

if (typeof document !== "undefined" && document.getElementById("dashboard")) {
  const stale = (message) => {
    document.getElementById("dashboard").dataset.stale = "true";
    const warning = document.getElementById("connection-warning"); warning.textContent = message; warning.hidden = false;
    const status = document.getElementById("worker-status");
    if (!status.textContent.startsWith("Last observed: ")) status.textContent = `Last observed: ${status.textContent}`;
  };
  attachDashboardLifecycle(window, () => startDashboardPolling({
    onState(snapshot) { renderDashboard(document, snapshot); },
    onError: stale,
  }), () => stale("Updates paused while this page was inactive. Waiting for a fresh observation from this worker."));
}
