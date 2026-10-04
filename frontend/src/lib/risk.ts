import type { RiskAssessment } from "./types";

const KEYS = ["alert", "basis", "confidenceLevel", "confidenceScore", "level", "limitations", "score", "summary", "title"];
export const riskLabels = { unknown: "Unknown", low: "Low", moderate: "Moderate", high: "High", critical: "Critical" } as const;

/** Accept only the bounded assessment supplied by Control; the UI never scores evidence. */
export function isRiskAssessment(value: unknown): value is RiskAssessment {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const risk = value as Record<string, unknown>;
  if (Object.keys(risk).sort().join(",") !== KEYS.join(",")
    || typeof risk.level !== "string" || !Object.hasOwn(riskLabels, risk.level)
    || !["low", "moderate", "high"].includes(String(risk.confidenceLevel))
    || typeof risk.confidenceScore !== "number" || !Number.isFinite(risk.confidenceScore)
    || risk.confidenceScore < 0 || risk.confidenceScore > 1
    || typeof risk.alert !== "boolean" || risk.alert !== ["high", "critical"].includes(risk.level)
    || !["title", "summary", "basis"].every((key) => typeof risk[key] === "string" && (risk[key] as string).trim().length > 0)
    || !Array.isArray(risk.limitations) || !risk.limitations.every((item) => typeof item === "string")) return false;
  return risk.level === "unknown" ? risk.score === null
    : typeof risk.score === "number" && Number.isFinite(risk.score) && risk.score >= 0 && risk.score <= 100;
}

export function optionalRisk(value: unknown): value is RiskAssessment | null | undefined { return value === undefined || value === null || isRiskAssessment(value); }

export function matchingRisk(a: RiskAssessment | null | undefined, b: RiskAssessment | null | undefined): boolean {
  if (a == null || b == null) return a == null && b == null;
  return KEYS.every((key) => JSON.stringify(a[key as keyof RiskAssessment]) === JSON.stringify(b[key as keyof RiskAssessment]));
}
