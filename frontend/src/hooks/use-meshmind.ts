"use client";

import { useCallback, useEffect, useState } from "react";
import { dataProvider, isDemoMode } from "@/lib/data-provider";
import { ControlApiError } from "@/lib/api-provider";
import type { AnalysisState, ControlConfig, SessionSummary } from "@/lib/types";

const message = (error: unknown, fallback: string) => error instanceof ControlApiError ? error.message : fallback;

export function useAnalysis(id: string) {
  const [analysis, setAnalysis] = useState<AnalysisState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async () => {
      if (!id) { setLoading(false); return; }
      let again = false;
      try {
        const result = await dataProvider.getAnalysis(id, controller.signal);
        if (controller.signal.aborted) return;
        setAnalysis(result); setError(null); setLoading(false);
        again = result?.status === "running";
      } catch (error) {
        if (controller.signal.aborted) return;
        setError(message(error, "This investigation could not be loaded.")); setLoading(false); again = true;
      }
      if (again && !controller.signal.aborted) timer = setTimeout(read, 1000);
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, revision]);
  return { analysis, loading, error, refresh };
}

export function useSessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async () => {
      try {
        const result = await dataProvider.listSessions(controller.signal);
        if (controller.signal.aborted) return;
        setSessions(result); setLoading(false); setError(null);
      } catch {
        if (controller.signal.aborted) return;
        setError("History is temporarily unavailable."); setLoading(false);
      }
      if (!controller.signal.aborted) timer = setTimeout(read, 3000);
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  return { sessions, loading, error };
}

export function useControlConfig() {
  const [config, setConfig] = useState<ControlConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (isDemoMode || !dataProvider.getConfig) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async () => {
      let again = false;
      try {
        const value = await dataProvider.getConfig!(controller.signal);
        if (controller.signal.aborted) return;
        setConfig(value); setError(null);
        again = !value.canStart;
      } catch (error) {
        if (controller.signal.aborted) return;
        setError(message(error, "Control configuration is unavailable.")); again = true;
      }
      // Recheck a busy Control after its current investigation finishes. Schedule
      // only after the preceding read settles, with cancellation on unmount.
      if (again && !controller.signal.aborted) timer = setTimeout(read, 3000);
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  return { config, error };
}
