"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { dataProvider, isDemoMode } from "@/lib/data-provider";

import { useControlConfig } from "@/hooks/use-meshmind";
import { ControlApiError } from "@/lib/api-provider";
import { InvestigationScope } from "./investigation-scope";

const MAX_LENGTH = 4000;

export function Composer({ compact = false, autoFocus = false }: { compact?: boolean; autoFocus?: boolean }) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  const { config, error: configError } = useControlConfig();
  const canStart = isDemoMode || config?.canStart === true;
  const promptRouting = config?.routingMode === "prompt";
  async function submit() {
    if (!prompt.trim() || busy || !canStart) return;
    setBusy(true); setError("");
    try { const id = await dataProvider.startAnalysis(prompt.trim()); router.push(`/session/${encodeURIComponent(id)}`); }
    catch (error) { setError(error instanceof ControlApiError ? error.message : "The investigation could not start. Please try again."); }
    finally { setBusy(false); }
  }
  const remaining = MAX_LENGTH - prompt.length;
  return <form className={`composer ${compact ? "composer--compact" : ""}`} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    {!isDemoMode && !compact && <div className="composer-scope">{config ? <InvestigationScope config={config} compact={compact} busy={busy} onExample={setPrompt} /> : <p role={configError ? "alert" : "status"}>{configError || "Reading investigation guidance…"}</p>}</div>}
    <label htmlFor="investigation-prompt" className="sr-only">{compact ? "Start a new investigation" : "Environmental investigation"}</label>
    <Textarea id="investigation-prompt" className="composer-input" autoFocus={autoFocus} placeholder={promptRouting || compact ? "Enter a location and dates to investigate flood risk…" : "Review rainfall, soil moisture, surface water, and terrain for the configured case…"} value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} maxLength={MAX_LENGTH} disabled={busy} />
    <div className="composer-toolbar">
      {remaining <= 200 && <p className={`composer-count ${remaining <= 0 ? "composer-limit" : ""}`} aria-live="polite">{remaining} characters left</p>}
      <Button type="submit" className="run-button" disabled={!prompt.trim() || busy || !canStart} aria-label={busy ? "Starting investigation" : "Run analysis"} title={!canStart ? "Control is not ready to start an investigation" : "Enter to run · Shift+Enter for a new line"}><span className={busy ? "shimmer" : undefined}>{busy ? "Starting…" : "Run analysis"}</span>{busy ? null : <><ArrowUp className="run-icon" size={15} weight="bold" aria-hidden="true"/><span className="run-key" aria-hidden="true">↵</span></>}</Button>
    </div>
    {compact && configError && <p className="form-error" role="alert">{configError}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}
