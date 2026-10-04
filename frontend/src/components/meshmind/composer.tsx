"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { dataProvider, isDemoMode } from "@/lib/data-provider";

import { useControlConfig } from "@/hooks/use-meshmind";
import { ControlApiError } from "@/lib/api-provider";

type Scenario = "happy" | "partial" | "validation-failed";
export function Composer({ compact = false }: { compact?: boolean }) {
  const [prompt, setPrompt] = useState("");
  const [scenario, setScenario] = useState<Scenario>("happy");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  const { config, error: configError } = useControlConfig();
  const canStart = isDemoMode || config?.canStart === true;
  async function submit() {
    if (!prompt.trim() || busy || !canStart) return;
    setBusy(true); setError("");
    try { const id = await dataProvider.startAnalysis(prompt.trim(), scenario); router.push(`/session/${encodeURIComponent(id)}`); }
    catch (error) { setError(error instanceof ControlApiError ? error.message : "The investigation could not start. Please try again."); }
    finally { setBusy(false); }
  }
  return <form className={`composer ${compact ? "composer--compact" : ""}`} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    {!isDemoMode && <div className="composer-scope">{config ? <><strong>{config.case.name}</strong><span>{config.case.requested_window.start} – {config.case.requested_window.end}</span><p>{config.notice}</p><p>Requests must use this configured area and time window.</p></> : <p role={configError ? "alert" : "status"}>{configError || "Reading configured investigation scope…"}</p>}</div>}
    <label htmlFor="investigation-prompt" className="sr-only">Environmental investigation</label>
    <Textarea id="investigation-prompt" className="composer-input" placeholder={compact ? "Ask about the configured historical case…" : "Review rainfall, soil moisture, surface water, and terrain for the configured case…"} value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} maxLength={4000} disabled={busy} />
    <div className="composer-toolbar">{isDemoMode && <div className="scenario-select"><label htmlFor="demo-scenario">Demo scenario</label><div className="select-wrap"><select id="demo-scenario" value={scenario} onChange={(event) => setScenario(event.target.value as Scenario)} disabled={busy}><option value="happy">Complete investigation</option><option value="partial">Laptop 3 unavailable</option><option value="validation-failed">Validation fails</option></select><ChevronDown size={13} aria-hidden="true"/></div></div>}<Button type="submit" className="run-button" disabled={!prompt.trim() || busy || !canStart} aria-label="Run Analysis"><span>{busy ? "Starting…" : "Run Analysis"}</span><ArrowUp size={18}/></Button></div>
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}
