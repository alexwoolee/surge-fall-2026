"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowDown, ArrowLeft, Check, Copy } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import { useAnalysis } from "@/hooks/use-meshmind";
import { ControlApiError } from "@/lib/api-provider";
import type { WorkerId } from "@/lib/types";
import { dataProvider } from "@/lib/data-provider";
import { riskLabels } from "@/lib/risk";
import { fullDate, sentAt } from "@/lib/format";
import { AgentStatus } from "./agent-status";
import { ActivityCard } from "./activity-card";
import { BriefingCard } from "./briefing-card";
import { PartialResultCard } from "./partial-result-card";
import { FailedCard, ValidationFailureCard } from "./validation-failure-card";
import { Composer } from "./composer";
import { Reveal } from "./reveal";
import { RiskSummary } from "./risk-summary";
import { sessionLabels } from "./session-badge";

/** Distance from the bottom (px) within which the transcript keeps following new activity. */
const STICK_THRESHOLD = 96;

export function SessionView({ id }: { id: string }) {
  const { analysis, loading, error, refresh } = useAnalysis(id);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showJump, setShowJump] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const scroller = scrollRef.current;
    if (scroller) scroller.scrollTo({ top: scroller.scrollHeight, behavior });
  }, []);

  // Open every investigation at its latest activity, then keep following growth
  // only while the reader is already at the bottom.
  const ready = Boolean(analysis);
  useLayoutEffect(() => {
    if (!ready) return;
    stickRef.current = true;
    scrollToBottom();
    const content = contentRef.current;
    if (!content) return;
    const observer = new ResizeObserver(() => { if (stickRef.current) scrollToBottom(); });
    observer.observe(content);
    return () => observer.disconnect();
  }, [ready, id, scrollToBottom]);

  useEffect(() => {
    if (analysis) document.title = `${analysis.title} · Amalga`;
  }, [analysis]);

  function onScroll() {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const atBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < STICK_THRESHOLD;
    stickRef.current = atBottom;
    setShowJump(!atBottom);
  }

  async function copyPrompt(text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1600); } catch { /* clipboard unavailable */ }
  }

  async function retryWorker(worker: WorkerId) {
    setRetrying(true);
    setRetryError(null);
    try {
      await dataProvider.retryWorker(id, worker);
      await refresh();
    } catch (error) {
      setRetryError(error instanceof ControlApiError ? error.message : "The investigation could not be retried.");
    } finally {
      setRetrying(false);
    }
  }

  if (loading) return <div className="view-empty-state" role="status"><span className="shimmer">Opening investigation…</span></div>;
  if (!analysis) return <div className="view-empty-state"><h1>{error ? "Unable to open this investigation" : "Investigation not found"}</h1><p>{error || "This investigation is not available in the current Control history."}</p><Button asChild variant="outline"><Link href="/">New investigation</Link></Button></div>;

  const phaseLabel = analysis.status === "briefing-ready" ? "Briefing ready" : analysis.status === "partial" ? "Review available" : analysis.status === "checks-failed" ? "Checks failed" : analysis.status === "failed" ? "Investigation failed" : !analysis.isDemo ? analysis.description : analysis.phase === "validating" ? "Control is validating returned evidence" : analysis.phase === "reviewing" ? "Control is evaluating review conditions" : "Specialist investigations in progress";

  return (
    <div className="session-layout">
      <header className="view-topbar session-topbar">
        <div className="session-heading">
          <div className="session-title-row"><span className={`status-dot status-dot--${analysis.status}`} title={sessionLabels[analysis.status]} aria-hidden="true" /><h1 className={analysis.status === "running" ? "shimmer" : undefined}>{analysis.title}</h1><span className="sr-only">, {sessionLabels[analysis.status]}</span></div>
          {analysis.risk && <span className={`session-risk-level session-risk-level--${analysis.risk.level}`} role={analysis.risk.alert ? "alert" : "status"}>{riskLabels[analysis.risk.level]} risk{analysis.risk.alert ? " · Attention required" : ""}</span>}
        </div>
        <div className="agent-status-row">
          <AgentStatus name="Control" location="Laptop 1" status={analysis.control} />
          {Object.values(analysis.workers).map((worker) => <AgentStatus key={worker.id} name={worker.name} location={worker.location} status={worker.status} />)}
        </div>
      </header>
      <div className="session-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="session-content" ref={contentRef}>
          {error && <p role="alert" className="inline-error">{error} Displaying the last received state. <button onClick={refresh}>Refresh</button></p>}
          <RiskSummary risk={analysis.risk} />
          {analysis.executionNotice && <p className="execution-notice">{analysis.executionNotice}</p>}
          <p className="sr-only" role="status" aria-live="polite">{phaseLabel}</p>
          <div className="prompt-message">
            <div className="prompt-bubble"><p>{analysis.prompt}</p></div>
            <div className="prompt-meta">
              <time dateTime={analysis.createdAt} title={fullDate(analysis.createdAt)}>Sent {sentAt(analysis.createdAt)}</time>
              <button type="button" className="meta-action" onClick={() => void copyPrompt(analysis.prompt)} aria-label={copied ? "Copied request" : "Copy request"} title={copied ? "Copied" : "Copy"}>{copied ? <Check size={14} /> : <Copy size={14} />}</button>
            </div>
          </div>
          <div className="context-pills"><span className="context-pill">{analysis.studyArea}</span><span className="context-pill">{analysis.requestedWindow}</span></div>
          <div className="session-activity" aria-label="Observable system activity">
            {analysis.activities.map((activity) => {
              const worker = Object.values(analysis.workers).find((candidate) => candidate.name === activity.name && candidate.location === activity.location);
              return <Reveal key={activity.id}><ActivityCard activity={activity} workerHref={worker ? `/worker/${worker.id}?session=${encodeURIComponent(id)}` : undefined} /></Reveal>;
            })}
          </div>
          {analysis.status === "running" && <div className="session-run-note"><span className="run-note-dot" aria-hidden="true" /><span className="shimmer">{phaseLabel}</span><span className="muted">Workers update independently</span></div>}
          {analysis.status === "briefing-ready" && <Reveal><BriefingCard analysis={analysis} /></Reveal>}
          {analysis.status === "partial" && <Reveal><PartialResultCard analysis={analysis} onRetry={retryWorker} retrying={retrying || analysis.retrying} /></Reveal>}
          {analysis.status !== "partial" && !analysis.retrying && analysis.retryableWorkers?.map((worker) => analysis.workers[worker] && <Button key={worker} variant="outline" onClick={() => void retryWorker(worker)} disabled={retrying}>Retry {analysis.workers[worker]?.name}</Button>)}
          {retryError && <p className="inline-error" role="alert">{retryError}</p>}
          {(analysis.status === "checks-failed" || Boolean(analysis.risk && analysis.validationFailures.length)) && <Reveal><ValidationFailureCard failures={analysis.validationFailures} /></Reveal>}
          {analysis.status === "failed" && <Reveal><FailedCard /></Reveal>}
          <Link className="text-action session-history-link" href="/history"><ArrowLeft size={14} aria-hidden="true" />All investigations</Link>
        </div>
      </div>
      <div className="session-dock">
        {showJump && <button type="button" className="jump-latest" onClick={() => scrollToBottom("smooth")}><ArrowDown size={14} />Jump to latest</button>}
        <div className="session-composer"><Composer compact /></div>
      </div>
    </div>
  );
}
