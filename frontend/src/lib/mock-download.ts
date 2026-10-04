import type { BriefingViewModel } from "./types";

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]!);
}

function table(headers: string[], rows: string[][]): string {
  return `<div class="table-wrap"><table><thead><tr>${headers.map((cell) => `<th scope="col">${escapeHtml(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

/** Pure, escaped HTML generation makes the demo download replaceable and testable. */
export function renderMockBriefingHtml(briefing: BriefingViewModel): string {
  const conditions = briefing.reviewConditions.map((condition) => [condition.id, condition.condition, condition.observed, condition.configured, condition.status === "triggered" ? "Analyst review recommended" : condition.status === "not-assessable" ? "Not assessable" : "Not triggered"]);
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <title>${escapeHtml(briefing.title)} — MeshMind ${briefing.partial ? "partial " : ""}briefing</title>
  <style>
    *{box-sizing:border-box}body{margin:0;background:#09090b;color:#ededee;font:15px/1.75 Arial,Helvetica,sans-serif}main{max-width:960px;margin:48px auto;padding:40px;background:#131315;border:1px solid #29292e;border-radius:20px}.brand{font-weight:700;letter-spacing:-.03em}.eyebrow,.notice,dt,th{color:#a1a1aa}h1{font-size:29px;line-height:1.25;letter-spacing:-.035em}h2{font-size:14px;color:#b4b4bc;margin-top:0}section{padding:26px 0;border-top:1px solid #29292e}p{margin:12px 0}dl{margin:28px 0}dl>div{display:grid;grid-template-columns:1fr 2fr;gap:24px;padding:12px 0;border-top:1px solid #29292e}dd{margin:0}.notice{border:1px solid #725626;background:#241e13;padding:12px 16px;border-radius:10px;color:#e8cf8a;font-size:13px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}th{font-weight:400}th,td{padding:12px 8px;border-bottom:1px solid #29292e;vertical-align:top}.disclaimer{border:1px solid #3a3a41;padding:16px;border-radius:10px;font-size:13px}li{margin-bottom:5px}.eyebrow{font:12px/1.8 monospace}.status{color:#eac566;font-size:13px}@media(max-width:650px){main{margin:0;border-radius:0;padding:24px}dl>div{grid-template-columns:1fr;gap:4px}}@media print{body,main{background:white;color:#111}main{border:0;margin:0;padding:0;max-width:none}h2,th,dt,.eyebrow{color:#444}.notice{background:#fff8e4;color:#49390c}section{break-inside:avoid}table{font-size:11px}.disclaimer{color:#111}}
  </style>
</head>
<body><main>
  <div class="brand">MeshMind</div>
  <p class="eyebrow">Environmental analysis · ${briefing.partial ? "Partial briefing" : "Final briefing"}</p>
  <h1>${escapeHtml(briefing.title)}</h1>
  <p class="notice">${escapeHtml(briefing.demoNotice)}</p>
  ${briefing.partial ? '<p class="status">Partial result — one investigation did not return. The other one still stands.</p>' : ""}
  <dl>${[["Original request", briefing.originalRequest], ["Study area", briefing.studyArea], ["Requested window", briefing.requestedWindow], ["Actual data coverage", briefing.actualCoverage]].map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
  ${briefing.sections.map((section) => `<section><h2>${escapeHtml(section.title)}</h2>${section.paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}</section>`).join("")}
  <section><h2>Analyst-review conditions</h2>${table(["Rule", "Condition", "Observed", "Configured", "Outcome"], conditions)}<p class="eyebrow">Configured criteria indicate when an analyst should review the evidence. They are not universal disaster thresholds.</p></section>
  <section><h2>Source provenance</h2>${table(["Dataset", "Access", "Resources", "Coverage"], briefing.sourceProvenance.map((source) => [source.dataset, source.access, source.resources, source.coverage]))}</section>
  <section><h2>Processing provenance</h2>${table(["Investigation", "Executed on", "Method", "Duration"], briefing.processingProvenance.map((source) => [source.investigation, source.location, source.method, source.duration]))}</section>
  <section><h2>Limitations</h2><ul>${briefing.limitations.map((limitation) => `<li>${escapeHtml(limitation)}</li>`).join("")}</ul></section>
  <p class="disclaimer">${escapeHtml(briefing.disclaimer)}</p>
</main></body></html>`;
}

/** Frontend-only download. Future production reports should come from Control. */
export function getMockBriefingDownload(briefing: BriefingViewModel) {
  return {
    href: `data:text/html;charset=utf-8,${encodeURIComponent(renderMockBriefingHtml(briefing))}`,
    filename: `meshmind-${briefing.partial ? "partial-" : ""}briefing-demo.html`,
  };
}
