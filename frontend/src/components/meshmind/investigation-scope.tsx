import type { ControlConfig } from "@/lib/types";

export function InvestigationScope({ config, compact, busy, onExample }: { config: ControlConfig; compact: boolean; busy: boolean; onExample: (prompt: string) => void }) {
  if (config.routingMode !== "prompt") return <><strong>{config.case.name}</strong><span>{config.case.requested_window.start} – {config.case.requested_window.end}</span><p>{config.notice}</p><p>Requests must use this configured area and time window.</p></>;
  return <><strong>Choose a location and date range</strong><p>{config.notice}</p>
    <p>Enter a historical date (YYYY-MM-DD) or an explicit date range. A single date covers that UTC day. Hydro and Flood query available observations at runtime; missing coverage remains visible.</p>
    <p>Hydrometeorology and Surface Water &amp; Terrain investigate each resolved request. Dam Condition joins only for Toddbrook Reservoir, Whaley Bridge, Derbyshire.</p>
    {!compact && config.examples && <div className="composer-examples" aria-label="Example investigations">{config.examples.map((example) => <button type="button" key={example} disabled={busy} onClick={() => onExample(example)}>{example}</button>)}</div>}
  </>;
}
