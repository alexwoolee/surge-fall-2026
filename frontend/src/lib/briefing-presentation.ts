import type { BriefingViewModel, RiskAssessment } from "./types";

// This is a display projection only. Retained measurements and rule outcomes stay intact.
const absentValues = new Set([
  "Unavailable.", "Unavailable", "Unavailable; zero is not substituted.",
  "Unavailable; no source result was returned.", "Not returned", "Not available",
]);
const routineSourceNotes = new Set([
  "The requested period predates this product.",
  "The catalog returned no eligible observations for the requested area and interval.",
  "Terrain excluded because its observation date cannot be verified against the historical cutoff.",
]);

export function amalgaDisplay(text: string): string {
  return text.replaceAll("MeshMind", "Amalga");
}

const routineRiskSentences = new Set([
  "DEM and HAND are unavailable, so local topographic screening cannot be applied here.",
]);

export function presentRiskText(text: string, level: RiskAssessment["level"]): string {
  if (level === "unknown") return amalgaDisplay(text);
  // Match a complete, known sentence only; mixed claims and measurements remain.
  const sentences = text.split(/(?<=[.!?])\s+/u);
  const retained = sentences.filter((sentence) => !routineRiskSentences.has(sentence));
  return amalgaDisplay(retained.length ? retained.join(" ") : text);
}

export function presentLimitations(limitations: string[]): string[] {
  return limitations.filter((text) => text !== "Missing evidence stays unavailable. It is not treated as zero or evidence of safety.").map(amalgaDisplay);
}

export function presentBriefing(briefing: BriefingViewModel) {
  const sources = briefing.sourceProvenance.filter((source) => !absentValues.has(source.resources))
    .map((source) => ({ ...source, dataset: amalgaDisplay(source.dataset), access: amalgaDisplay(source.access), coverage: amalgaDisplay(source.coverage.replace("Only part of the requested rainfall interval is available.", "").trim()) }));
  const operationalSources = briefing.sourceProvenance.filter((source) =>
    absentValues.has(source.resources) && !routineSourceNotes.has(source.coverage))
    .map((source) => ({ ...source, dataset: amalgaDisplay(source.dataset), coverage: amalgaDisplay(source.coverage) }));
  return {
    metrics: briefing.metrics.filter((metric) => !absentValues.has(metric.value)).map((metric) => ({ ...metric, label: amalgaDisplay(metric.label) })),
    conditions: briefing.reviewConditions.filter((condition) => condition.status !== "not-assessable")
      .map((condition) => ({ ...condition, condition: amalgaDisplay(condition.condition), observed: amalgaDisplay(condition.observed), configured: amalgaDisplay(condition.configured) })),
    sources,
    operationalSources,
    limitations: presentLimitations(briefing.limitations),
    actualCoverage: sources.map((source) => `${source.dataset}: ${source.coverage}`).join(" "),
    // The opening assessment already includes this summary and basis.
    sections: briefing.sections.filter((section) => !briefing.risk || section.id !== "risk")
      .map((section) => ({ ...section, title: amalgaDisplay(section.title), paragraphs: section.paragraphs.map(amalgaDisplay) })),
    processing: briefing.processingProvenance.map((process) => ({ ...process, investigation: amalgaDisplay(process.investigation), location: amalgaDisplay(process.location), method: amalgaDisplay(process.method), duration: amalgaDisplay(process.duration) })),
  };
}
