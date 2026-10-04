"use client";

import { useCallback, useEffect, useState } from "react";
import { dataProvider } from "@/lib/data-provider";
import type { AnalysisState, SessionSummary } from "@/lib/types";

export function useAnalysis(id: string) {
  const [analysis, setAnalysis] = useState<AnalysisState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    let cancelled = false;
    const read = async () => {
      try {
        const result = await dataProvider.getAnalysis(id);
        if (!cancelled) { setAnalysis(result); setError(null); setLoading(false); }
      } catch {
        if (!cancelled) { setError("This investigation could not be loaded. Please try again."); setLoading(false); }
      }
    };
    void read();
    const interval = window.setInterval(read, 400);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [id, revision]);
  return { analysis, loading, error, refresh };
}

export function useSessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const read = async () => {
      try {
        const result = await dataProvider.listSessions();
        if (!cancelled) { setSessions(result); setLoading(false); setError(null); }
      } catch {
        if (!cancelled) { setError("History is temporarily unavailable."); setLoading(false); }
      }
    };
    void read();
    const interval = window.setInterval(read, 1000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, []);
  return { sessions, loading, error };
}
