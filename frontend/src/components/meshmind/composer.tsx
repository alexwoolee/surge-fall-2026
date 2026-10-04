"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { dataProvider } from "@/lib/data-provider";

type Scenario = "happy" | "partial" | "validation-failed";
export function Composer({ compact = false }: { compact?: boolean }) {
  const [prompt, setPrompt] = useState("");
  const [scenario, setScenario] = useState<Scenario>("happy");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  async function submit() {
    if (!prompt.trim() || busy) return;
    setBusy(true); setError("");
    try { const id = await dataProvider.startAnalysis(prompt.trim(), scenario); router.push(`/session/${encodeURIComponent(id)}`); }
    catch { setError("The demo could not start. Please try again."); }
    finally { setBusy(false); }
  }
  return <form className={`composer ${compact ? "composer--compact" : ""}`} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    <label htmlFor="investigation-prompt" className="sr-only">Environmental investigation</label>
    <Textarea id="investigation-prompt" className="composer-input" placeholder={compact ? "Ask a new environmental question…" : "Ask anything about rainfall, soil moisture, or surface water…"} value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} maxLength={4000} disabled={busy} />
    <div className="composer-toolbar"><div className="scenario-select"><label htmlFor="demo-scenario">Demo scenario</label><div className="select-wrap"><select id="demo-scenario" value={scenario} onChange={(event) => setScenario(event.target.value as Scenario)} disabled={busy}><option value="happy">Complete investigation</option><option value="partial">Laptop 3 unavailable</option><option value="validation-failed">Validation fails</option></select><ChevronDown size={13} aria-hidden="true"/></div></div><Button type="submit" className="run-button" disabled={!prompt.trim() || busy} aria-label="Run Analysis"><span>{busy ? "Starting…" : "Run Analysis"}</span><ArrowUp size={18}/></Button></div>
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}
