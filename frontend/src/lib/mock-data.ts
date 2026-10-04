import type { BriefingViewModel, DemoScenario, ReviewCondition, ValidationFailure, WorkerId } from "./types";

/** All sample measurements, provenance, timings, and scientific prose live here. */
export const DEMO_NOTICE = "Demo data · Simulated workflow. These example observations are not a live environmental assessment.";
export const DISCLAIMER = "MeshMind is an environmental analysis and analyst-support system. It is not an operational emergency-response or evacuation system.";

export const AGENTS = {
  control: { name: "Control", location: "Laptop 1", resources: [] as string[] },
  hydro: { name: "Hydrometeorology Agent", location: "Laptop 2", resources: ["GPM IMERG", "SMAP L4"] },
  flood: { name: "Surface Water & Terrain Agent", location: "Laptop 3", resources: ["Sentinel-1 SAR", "Copernicus DEM", "HAND"] },
} as const;

export const DEMO_SCENARIOS: { id: DemoScenario; label: string; description: string }[] = [
  { id: "happy", label: "Complete investigation", description: "Both specialists return; Control validates the evidence and prepares a briefing." },
  { id: "partial", label: "Laptop 3 unavailable", description: "Hydrometeorology completes while Surface Water & Terrain becomes unreachable." },
  { id: "validation-failed", label: "Validation failure", description: "Returned surface-water evidence fails coverage and freshness checks." },
  { id: "failed", label: "Investigation failed", description: "The simulated request cannot reach either specialist." },
];

export const DEMO_TIMING = {
  hydroComplete: 7_000,
  floodComplete: 9_000,
  validating: 10_000,
  reviewing: 11_000,
  ready: 12_000,
  floodDown: 5_000,
  dispatchFailed: 2_000,
  initial: 1_000,
  seededRunning: 5_000,
} as const;

export interface MockRecord {
  id: string;
  title: string;
  prompt: string;
  area: string;
  createdAt: number;
  startedAt: number;
  scenario: DemoScenario;
  frozenElapsedMs?: number;
  retryStartedAt?: number;
}

export const DEMO_AREA = "Abbotsford / Sumas Prairie, British Columbia";
export const DEMO_PROMPT = "Assess flood susceptibility around Abbotsford after the recent rainfall and prepare a briefing.";
export const DEMO_WINDOW = "2026-09-26 → 2026-10-03 (7 days)";
export const DEMO_COVERAGE = "GPM: Sep 26–Oct 3 · SMAP: Sep 26–Oct 2 · Sentinel-1: Oct 1, 19:42 UTC · terrain: static";
export const PARTIAL_COVERAGE = "GPM: Sep 26–Oct 3 · SMAP: Sep 26–Oct 2 · surface-water and terrain evidence unavailable";

export function createDemoRecords(now: number): MockRecord[] {
  const minute = 60_000;
  const day = 24 * 60 * minute;
  const records: Omit<MockRecord, "startedAt">[] = [
    { id: "running", title: "Sumas Prairie follow-up", prompt: "Review the latest rainfall and surface-water observations for Sumas Prairie.", area: DEMO_AREA, createdAt: now - 2 * minute, scenario: "happy", frozenElapsedMs: DEMO_TIMING.seededRunning },
    { id: "ready", title: "Abbotsford rainfall & flood susceptibility", prompt: DEMO_PROMPT, area: DEMO_AREA, createdAt: now - 12 * minute, scenario: "happy", frozenElapsedMs: DEMO_TIMING.ready },
    { id: "partial", title: "Richmond river reach", prompt: "Review flood susceptibility along the Richmond river reach after recent rainfall.", area: "Richmond river reach, British Columbia", createdAt: now - day, scenario: "partial", frozenElapsedMs: DEMO_TIMING.ready },
    { id: "checks-failed", title: "Lower Fraser flood review", prompt: "Prepare an evidence briefing for the Lower Fraser floodplain.", area: "Lower Fraser floodplain, British Columbia", createdAt: now - day - 3 * 60 * minute, scenario: "validation-failed", frozenElapsedMs: DEMO_TIMING.ready },
    { id: "failed", title: "Fraser Valley rainfall follow-up", prompt: "Investigate rainfall and terrain context across the Fraser Valley.", area: "Fraser Valley, British Columbia", createdAt: now - 3 * day, scenario: "failed", frozenElapsedMs: DEMO_TIMING.ready },
  ];
  return records.map((record) => ({ ...record, startedAt: record.createdAt }));
}

export const WORKER_STEPS: Record<WorkerId, { id: string; label: string; at: number }[]> = {
  hydro: [
    { id: "received", label: "Task received", at: 0 },
    { id: "gpm", label: "Locate GPM IMERG observations", at: 1_000 },
    { id: "smap", label: "Locate SMAP L4 state", at: 2_000 },
    { id: "rainfall", label: "Calculate rainfall accumulation", at: 3_000 },
    { id: "soil", label: "Calculate soil-moisture state", at: 5_000 },
    { id: "prepare", label: "Prepare hydrometeorology result", at: 6_000 },
    { id: "return", label: "Return result to Control", at: 6_500 },
  ],
  flood: [
    { id: "received", label: "Task received", at: 0 },
    { id: "sentinel", label: "Locate Sentinel-1 scene", at: 1_000 },
    { id: "dem", label: "Locate Copernicus DEM tiles", at: 2_000 },
    { id: "hand", label: "Locate HAND tiles", at: 2_500 },
    { id: "sar", label: "Read SAR observation", at: 3_000 },
    { id: "terrain", label: "Calculate terrain context", at: 5_000 },
    { id: "prepare", label: "Prepare surface-water and terrain result", at: 7_000 },
    { id: "return", label: "Return result to Control", at: 8_000 },
  ],
};

export const WORKER_EVENTS: Record<WorkerId, { at: number; text: string }[]> = {
  hydro: [
    { at: 0, text: "Task received." },
    { at: 1_000, text: "Searching GPM IMERG. Rainfall observations located." },
    { at: 2_000, text: "SMAP L4 surface and root-zone observations located." },
    { at: 3_000, text: "Calculating rainfall accumulation over the study area." },
    { at: 5_000, text: "Calculating surface and root-zone soil-moisture state." },
    { at: 6_000, text: "Preparing hydrometeorology evidence and source provenance." },
    { at: DEMO_TIMING.hydroComplete, text: "Hydrometeorology result returned to Control." },
  ],
  flood: [
    { at: 0, text: "Task received." },
    { at: 1_000, text: "Sentinel-1 observation located for the study area." },
    { at: 2_000, text: "Intersecting Copernicus DEM and HAND tiles located." },
    { at: 3_000, text: "Reading the SAR observation for candidate surface-water evidence." },
    { at: 5_000, text: "Calculating elevation and drainage-relative terrain context." },
    { at: 7_000, text: "Preparing surface-water evidence and terrain provenance." },
    { at: DEMO_TIMING.floodComplete, text: "Surface-water and terrain result returned to Control." },
  ],
};

export const VALIDATION_FAILURES: ValidationFailure[] = [
  { title: "Coverage", detail: "Only 61% of the requested study area returned usable surface-water observations. The result does not meet the configured coverage requirement." },
  { title: "Freshness", detail: "The newest usable surface-water observation falls outside the requested time window." },
];

const REVIEW_CONDITIONS: ReviewCondition[] = [
  { id: "R-01", condition: "Peak 24-hour rainfall above the configured threshold", observed: "61.2 mm", configured: "90 mm", status: "not-triggered" },
  { id: "R-02", condition: "Rainfall accumulation above the configured review threshold", observed: "148.6 mm", configured: "120 mm", status: "triggered" },
  { id: "R-03", condition: "Surface soil moisture above the configured saturation proxy", observed: "0.41 m³/m³", configured: "0.45 m³/m³", status: "not-triggered" },
  { id: "R-04", condition: "Candidate surface water overlaps low-HAND terrain", observed: "62%", configured: "50%", status: "triggered" },
  { id: "R-05", condition: "Candidate surface-water extent above the configured area threshold", observed: "7.9 km²", configured: "15 km²", status: "not-triggered" },
];

export function demoReviewConditions(partial: boolean): ReviewCondition[] {
  return REVIEW_CONDITIONS.map((condition) => partial && ["R-04", "R-05"].includes(condition.id)
    ? { ...condition, observed: "Not available", status: "not-assessable" }
    : { ...condition });
}

export function createMockBriefing(record: MockRecord, partial: boolean): BriefingViewModel {
  const hydroSections = [
    { id: "rainfall", title: "Rainfall observations — GPM IMERG", paragraphs: [
      "Seven-day rainfall accumulation over the sample study area is 148.6 mm. The heaviest 24-hour accumulation is 61.2 mm on September 30. All selected observations in this demonstration are marked usable.",
      "Antecedent context: the preceding seven days in this fixture contain 38.1 mm of rainfall. These are example measurements supplied by the frontend demo provider.",
    ] },
    { id: "soil", title: "Soil-moisture observations — SMAP L4", paragraphs: [
      "Surface soil moisture at the end of the sample window averages 0.41 m³/m³. Root-zone soil moisture averages 0.38 m³/m³. These are state observations, not accumulated rainfall measurements.",
      "The sample land-state observation provides supporting context for the rainfall evidence. SMAP's coarse resolution does not describe conditions at an individual property.",
    ] },
  ];
  const floodSections = partial ? [
    { id: "surface-water", title: "Candidate surface water — not available", paragraphs: ["The Surface Water & Terrain investigation did not return a result after Laptop 3 became unreachable. No candidate surface-water measurement is available."] },
    { id: "terrain", title: "Terrain context — not available", paragraphs: ["Copernicus DEM and HAND context did not return. No terrain inference has been made from the missing investigation."] },
  ] : [
    { id: "surface-water", title: "Candidate surface water — Sentinel-1 SAR", paragraphs: [
      "A single VV observation from October 1 yields a candidate surface-water extent of 7.9 km² within the sample study area, derived using a fixed backscatter threshold.",
      "This is an example surface-water signal from one observation. It is not a confirmed flood extent and has not been validated against gauges or field observations.",
    ] },
    { id: "terrain", title: "Terrain context — Copernicus DEM and HAND", paragraphs: [
      "Elevation in the sample area ranges from 3 m to 112 m, with a mean of 18 m. Of the candidate surface water, 62% lies below 5 m HAND, indicating drainage-relative low-lying ground.",
      "HAND is supporting terrain context. Low HAND does not establish inundation, water depth, or impact.",
    ] },
  ];
  return {
    title: `Flood susceptibility, ${record.area}`,
    originalRequest: record.prompt,
    studyArea: record.area,
    requestedWindow: DEMO_WINDOW,
    actualCoverage: partial ? PARTIAL_COVERAGE : DEMO_COVERAGE,
    partial,
    demoNotice: DEMO_NOTICE,
    sections: [
      ...hydroSections,
      ...floodSections,
      { id: "combined", title: "Combined observations", paragraphs: partial ? [
        "The hydrometeorology result completed, validated, and was retained. Rainfall and soil-moisture observations remain available independently of the missing surface-water and terrain investigation.",
        "Surface-water and terrain evidence is unavailable. Conditions depending on it are not assessable and have not been counted as passing.",
      ] : [
        "The sample rainfall, soil-moisture state, and candidate surface-water signal are mutually consistent with a need for analyst review. Two independent specialist investigations contribute to this demonstration briefing.",
        "The evidence does not establish water depth or duration, whether the observed water is still present, or consequences for specific assets or populations.",
      ] },
    ],
    metrics: [
      { label: "Rainfall accumulation", value: "148.6 mm" },
      { label: "Peak 24-hour rainfall", value: "61.2 mm" },
      { label: "Surface soil moisture", value: "0.41 m³/m³" },
      { label: "Root-zone soil moisture", value: "0.38 m³/m³" },
    ],
    reviewConditions: demoReviewConditions(partial),
    sourceProvenance: [
      { dataset: "GPM IMERG", access: "earthaccess · demo", resources: "1,344 granules", coverage: "Sep 26 → Oct 3" },
      { dataset: "SMAP L4", access: "earthaccess · demo", resources: "56 observations", coverage: "Sep 26 → Oct 2" },
      { dataset: "Sentinel-1 GRD", access: "Provider/access to be supplied by backend", resources: partial ? "Not returned" : "1 scene", coverage: partial ? "Not available" : "Oct 1, 19:42 UTC" },
      { dataset: "Copernicus DEM", access: "STAC / raster access · demo", resources: partial ? "Not returned" : "2 tiles", coverage: partial ? "Not available" : "Static terrain" },
      { dataset: "HAND", access: "ASF STAC / public S3 · demo", resources: partial ? "Not returned" : "2 tiles", coverage: partial ? "Not available" : "Static terrain" },
    ],
    processingProvenance: [
      { investigation: "Hydrometeorology", location: "Laptop 2", method: "Rainfall accumulation; surface and root-zone state", duration: "7 s · simulated" },
      { investigation: "Surface Water & Terrain", location: "Laptop 3", method: partial ? "No result returned" : "Candidate-water threshold; DEM and HAND context", duration: partial ? "Unavailable" : "9 s · simulated" },
      { investigation: "Validation, fusion, review rules", location: "Laptop 1", method: "Configured validation and review conditions", duration: "3 s · simulated" },
    ],
    limitations: [
      "This is a frontend demonstration. No remote workers or environmental data sources were contacted.",
      "One Sentinel-1 observation and one polarisation cannot separate recent change from permanent water.",
      "A fixed backscatter threshold is sensitive to radar shadow, smooth dry surfaces, and wind-roughened water.",
      "SMAP resolution is coarse relative to the study area and cannot identify conditions at a specific property.",
      "HAND describes drainage-relative terrain. Low-lying does not mean inundated.",
      "No gauge, field, or independent imagery validation was performed in this example.",
      ...(partial ? ["Surface-water and terrain evidence is missing. Dependent review conditions are not assessable."] : []),
      "Configured review thresholds are deployment-specific criteria for analyst attention, not universal scientific disaster thresholds.",
    ],
    disclaimer: DISCLAIMER,
  };
}
