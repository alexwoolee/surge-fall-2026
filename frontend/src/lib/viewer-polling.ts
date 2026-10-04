import type { WorkerId, WorkerViewerSnapshot } from "./types";
import { parseViewerSnapshot } from "./viewer-contract";

interface ViewerPollingOptions {
  onSnapshot: (snapshot: WorkerViewerSnapshot) => void;
  onError: (message: string) => void;
  fetcher?: typeof fetch;
  schedule?: (callback: () => void, delay: number) => () => void;
}
/** Follow authoritative snapshots forever, including between completed runs. */
export function followWorker(role: WorkerId, options: ViewerPollingOptions): () => void {
  const controller = new AbortController(); let cancelTimer: (() => void) | undefined;
  const schedule = options.schedule ?? ((callback, delay) => { const timer = setTimeout(callback, delay); return () => clearTimeout(timer); });
  const read = async () => {
    let delay = 1000;
    try {
      const response = await (options.fetcher ?? fetch)(`/api/viewer/${role}`, { method: "GET", credentials: "same-origin", cache: "no-store", redirect: "error", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]) });
      if (!response.ok) throw new Error("Viewer unavailable");
      const snapshot = parseViewerSnapshot(await response.json(), role);
      if (controller.signal.aborted) return;
      options.onSnapshot(snapshot);
    } catch {
      if (controller.signal.aborted) return;
      options.onError("Updates are unavailable. Any evidence below is the last received state. Reconnect or reload to authenticate again.");
      delay = 3000;
    }
    if (!controller.signal.aborted) cancelTimer = schedule(() => { void read(); }, delay);
  };
  void read();
  return () => { controller.abort(); cancelTimer?.(); };
}
