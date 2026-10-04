"""Allow a model to select facts, never to author environmental conclusions.

Only fixed templates, validated measurements and normalized timestamps cross
the model boundary. Raw evidence stays in the separately retained Phase 7
report. The returned narrative is rendered by Python even after API failure.
"""

from datetime import datetime, timezone
import json

from pydantic import BaseModel

from backend.control.alerts import DEMO_NOTICE, ReviewPolicy, ReviewResult, evaluate_review_conditions
from backend.control.fusion import DISCLAIMER, FusionResult
from backend.control.explanation_methods import build_method_facts


MAX_SELECTED_FACTS = 16
_COMPARATORS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_NAMES = {"gpm": "GPM", "smap": "SMAP", "sentinel1": "Sentinel-1",
          "dem": "DEM", "hand": "HAND"}
_COVERAGE_METRICS = (
    "gpm.mean_accumulation_mm", "smap.surface_mean_m3_m3",
    "smap.rootzone_mean_m3_m3", "sentinel1.valid_fraction", "dem.mean_m", "hand.mean_m",
)
_LIMITATIONS = (
    "Evidence is combined at the requested AOI level. Native grids, valid coverage and observation dates differ; no spatial water/terrain overlay is performed.",
    "Processing completion does not imply complete spatial or temporal coverage. Missing observations are not extrapolated or replaced with zero.",
    "GPM duration is the sum represented by supplied granules; validated interval boundaries and temporal continuity are not reported by the current worker.",
    "One SMAP state and one Sentinel-1 acquisition do not establish change, event evolution, causation, future conditions or confirmed flooding.",
    "DEM and HAND describe terrain across their available AOI cells, not specifically candidate-water pixels. Water depth, water-on-low-HAND fraction and severity are not calculated.",
    "Worker execution times describe processing, not environmental observation times. Dispatch mode alone is not proof of physical parallel execution.",
)


class GroundingValidationError(ValueError):
    """A report or model selection cannot safely be used for explanation."""


def _json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError


def _validated_report(report):
    """Revalidate detached evidence and recompute every policy assessment.

    This proves internal binding and consistency, not authenticity of the
    original observations. The caller retains the source acquisition evidence.
    Validation errors are fixed text so hostile payloads cannot escape in logs.
    """
    try:
        if not isinstance(report, dict):
            raise ValueError
        detached = json.loads(json.dumps(report, default=_json_default, allow_nan=False))
        fused = FusionResult.model_validate(detached["fusion"])
        review = ReviewResult.model_validate(detached["review"])
        policy = ReviewPolicy.model_validate(review.policy.model_dump(mode="python"))
        if review != evaluate_review_conditions(fused, policy):
            raise ValueError
        return detached, fused, review
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise GroundingValidationError("The retained report does not satisfy its evidence and review contracts.") from None


def _timestamp(value):
    """Only called with a timestamp already validated by a typed summary."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _catalog(fused, review):
    facts = {}

    def add(fact_id, text, kind, *source_refs):
        facts[fact_id] = {"id": fact_id, "text": text,
                          "source_refs": list(source_refs), "kind": kind}

    for metric_id, metric in fused.metrics.items():
        ref = f"/fusion/metrics/{metric_id}"
        if metric.status == "available":
            text = f"{metric.label}: {metric.value!r} {metric.unit}."
            kind = "measurement"
        else:
            text = f"{metric.label}: unavailable; no measurement is available and zero is not substituted."
            kind = "unavailable"
        add(f"metric.{metric_id}", text, kind, ref)

    for index, assessment in enumerate(review.assessments, 1):
        metric = fused.metrics[assessment.metric]
        observed = ("unavailable" if assessment.value is None
                    else f"{assessment.value!r} {assessment.unit}")
        # Rule IDs and labels are operator text and may contain private data;
        # ordinal references preserve the mapping without sending those strings.
        text = (f"Demonstration condition {index}: {metric.label} "
                f"{_COMPARATORS[assessment.comparator]} {assessment.threshold!r} {assessment.unit}. "
                f"Observed: {observed}. Outcome: {assessment.status}. ")
        if assessment.required_duration_hours is not None:
            text += f"Required supplied duration: {assessment.required_duration_hours!r} hours. "
        if assessment.minimum_valid_fraction is not None:
            text += f"Minimum valid fraction: {assessment.minimum_valid_fraction!r}. "
        # This reason is checked against a newly computed result above, whose
        # reasons are fixed templates rather than source/worker error messages.
        text += assessment.reason
        add(f"rule.{index}", text, "rule", f"/review/assessments/{index - 1}",
            f"/fusion/metrics/{assessment.metric}")

    if fused.requested_window is None:
        text = "The requested environmental time window is unreported."
    else:
        text = (f"Requested environmental time window: {_timestamp(fused.requested_window.start)} "
                f"to {_timestamp(fused.requested_window.end)}. "
                "This user context does not establish that any source covers the whole window.")
    add("time.requested", text, "time", "/fusion/requested_window")
    gpm = fused.metrics["gpm.mean_accumulation_mm"]
    text = ("GPM supplied observation duration is unavailable." if gpm.duration_hours is None
            else f"GPM supplied observation duration: {gpm.duration_hours!r} hours, summed across supplied granules.")
    text += " Validated interval boundaries and temporal continuity are unknown; this is not a whole-event total."
    add("time.gpm", text, "time", "/fusion/components/gpm/time_basis")
    for component in ("smap", "sentinel1"):
        item = fused.components[component]
        observed = item.time_basis.get("observed_at")
        if observed is None:
            text = f"{_NAMES[component]} observation timestamp is unavailable."
        else:
            basis = "single state timestamp from the resource filename" if component == "smap" else "single scene acquisition"
            text = f"{_NAMES[component]} {basis}: {_timestamp(observed)}."
        text += " One observation does not establish a temporal trend or complete event coverage."
        add(f"time.{component}", text, "time", f"/fusion/components/{component}/time_basis")
    task = fused.requests[1]
    add("time.sentinel1_search", (f"Sentinel-1 search window: {_timestamp(task.start_time)} "
                                  f"to {_timestamp(task.end_time)}; search bounds are not observation coverage."),
        "time", "/fusion/requests/1/start_time", "/fusion/requests/1/end_time")
    for component in ("dem", "hand"):
        status = "available" if fused.components[component].status == "available" else "unavailable"
        add(f"time.{component}", f"{_NAMES[component]} static terrain evidence is {status}; no observation or product timestamp is supplied.",
            "time", f"/fusion/components/{component}/time_basis")

    for metric_id in _COVERAGE_METRICS:
        metric = fused.metrics[metric_id]
        coverage = "unreported" if metric.valid_fraction is None else repr(metric.valid_fraction)
        text = f"{metric.label}: valid AOI pixel fraction is {coverage}."
        if metric.valid_fraction is not None and metric.valid_fraction < 1:
            text += " Spatial coverage is partial; uncovered or invalid cells are not extrapolated."
        if metric.component == "gpm":
            text += " Coverage requires valid pixels in every supplied granule."
        elif metric.component == "smap":
            text += " This is a grid-pixel fraction, not a geographic-area fraction."
        elif metric.component in {"dem", "hand"}:
            text += " This terrain coverage describes the AOI, not candidate-water pixels."
        add(f"coverage.{metric_id}", text, "coverage", f"/fusion/metrics/{metric_id}/valid_fraction")

    for index, text in enumerate(_LIMITATIONS):
        add(f"limitation.{index + 1}", text, "limitation", f"/fusion/limitations/{index}")
    add("policy.notice", DEMO_NOTICE, "limitation", "/review/notice")
    add("disclaimer", DISCLAIMER, "disclaimer", "/fusion/disclaimer")
    return facts


def build_fact_catalog(phase7_report: dict) -> dict[str, dict]:
    """Return only safe, source-referenced facts suitable for a model request."""
    _, fused, review = _validated_report(phase7_report)
    return _catalog(fused, review)


def explanation_schema(catalog: dict) -> dict:
    """Schema limits the model to a bounded list of already grounded fact IDs."""
    if not isinstance(catalog, dict) or not catalog or any(not isinstance(key, str) for key in catalog):
        raise GroundingValidationError("A nonempty fact catalog is required.")
    return {
        "type": "object", "properties": {
            "selected_fact_ids": {"type": "array", "items": {"type": "string", "enum": list(catalog)},
                                  "minItems": 1, "maxItems": MAX_SELECTED_FACTS},
        }, "required": ["selected_fact_ids"], "additionalProperties": False,
    }


def _display_context(fused, study_area_name, original_request, execution_mode):
    """Keep optional operator/request text local and explicitly outside evidence.

    JSON quoting keeps line breaks and quotes visibly inside the user quotation.
    A future HTML consumer must still escape all text rather than interpret it.
    """
    if (study_area_name is not None and (
            not isinstance(study_area_name, str) or not 1 <= len(study_area_name.strip()) <= 120
            or any(ord(char) < 32 or ord(char) == 127 for char in study_area_name))):
        raise GroundingValidationError("Study area display context must be bounded text.")
    if (original_request is not None and (
            not isinstance(original_request, str) or not original_request.strip()
            or len(original_request.encode("utf-8")) > 4096
            or any(ord(char) < 32 and char not in "\n\t" for char in original_request))):
        raise GroundingValidationError("Original request context must be bounded text.")
    if execution_mode not in (None, "review", "execute"):
        raise GroundingValidationError("Execution context must identify review or execute mode.")
    bbox = fused.bbox.model_dump(mode="json")
    lines = ["Study area (configured label): " + json.dumps(study_area_name, ensure_ascii=False) + "."
             if study_area_name is not None else "Study area label: unreported."]
    lines.append("Study area bounds in degrees (WGS84): " + ", ".join(
        f"{key} {bbox[key]!r}" for key in ("west", "south", "east", "north")) + ".")
    lines.append("Original request (untrusted user context, not an environmental finding): "
                 + json.dumps(original_request, ensure_ascii=False)
                 if original_request is not None
                 else "Original request: not retained; request saving was not enabled.")
    if execution_mode == "review":
        lines.append("Execution context: review of retained worker evidence; no new worker dispatch or data acquisition is represented by this explanation.")
    elif execution_mode == "execute":
        lines.append("Execution context: results of the caller-authorized worker investigation. Physical parallel execution requires separate identity and timing evidence; it is not inferred here.")
    else:
        lines.append("Execution context: unreported; this explanation does not establish a new worker execution or physical parallelism.")
    return {
        "study_area_name": study_area_name, "bbox": bbox,
        "original_request": original_request, "request_retained": original_request is not None,
        "execution_mode": execution_mode,
        "text": "\n\n".join(lines),
    }


def render_explanation(report: dict, selected_fact_ids: list[str] | None, *, status="complete",
                       study_area_name=None, original_request=None, execution_mode=None) -> dict:
    """Render model-selected highlights and an unskippable evidence context.

    None selects every measurement and condition for deterministic fallback;
    the model selection bound applies only to an explicit model-provided list.
    Every measurement, method, limit and rule remains in the full narrative
    independently of highlights. Display context and method facts are local;
    they do not expand the model-facing catalog. Original request retention is
    explicit and labels that text as user context, never validated evidence.
    Neither this function nor the model edits the report.
    """
    if status not in {"complete", "fallback"}:
        raise GroundingValidationError("Explanation status must be complete or fallback.")
    detached, fused, review = _validated_report(report)
    context = _display_context(fused, study_area_name, original_request, execution_mode)
    catalog = _catalog(fused, review)
    if selected_fact_ids is None:
        selected = [key for key, fact in catalog.items() if fact["kind"] in {"measurement", "unavailable", "rule"}]
    else:
        if (not isinstance(selected_fact_ids, list) or not 1 <= len(selected_fact_ids) <= MAX_SELECTED_FACTS
                or any(not isinstance(key, str) or key not in catalog for key in selected_fact_ids)
                or len(set(selected_fact_ids)) != len(selected_fact_ids)):
            raise GroundingValidationError("The explanation selection must contain unique known fact IDs within its limit.")
        selected = list(selected_fact_ids)
    highlights = [catalog[key] for key in selected]
    mandatory = [fact for fact in catalog.values()
                 if fact["kind"] in {"measurement", "time", "coverage", "limitation", "disclaimer", "unavailable"}]
    methods = build_method_facts(fused)
    mandatory.extend(methods)
    outcomes = [fact for fact in catalog.values() if fact["kind"] == "rule"]
    available = sum(item.status == "available" for item in fused.components.values())
    combined = {
        "id": "combined.summary", "kind": "summary",
        "text": (f"Combined observations: {available} of {len(fused.components)} source components have validated results. "
                 f"Demonstration review conditions: {review.triggered_count} triggered, "
                 f"{review.not_triggered_count} not triggered, {review.not_assessable_count} not assessable. "
                 "These are configured analyst-review criteria, not a flood confirmation or severity classification. "
                 "Component availability does not imply full coverage or simultaneous observations."),
        "source_refs": ["/fusion/status", "/review/triggered_count", "/review/not_triggered_count",
                        "/review/not_assessable_count"],
    }
    mandatory.append(combined)
    sections = [{"id": "context", "title": "Study area and request", "text": context["text"],
                 "source_refs": ["/fusion/bbox"]}]

    def section(section_id, title, facts):
        sections.append({"id": section_id, "title": title,
                         "text": "\n\n".join(fact["text"] for fact in facts),
                         "source_refs": list(dict.fromkeys(ref for fact in facts for ref in fact["source_refs"]))})

    section("combined", "Combined observations", [combined, catalog["policy.notice"]])
    section("measurements", "Environmental measurements", [catalog[f"metric.{key}"] for key in fused.metrics])
    section("conditions", "Analyst-review conditions", outcomes)
    section("observation_context", "Observation times and coverage",
            [fact for fact in catalog.values() if fact["kind"] in {"time", "coverage"}])
    section("methods", "Sources and processing", [fact for fact in methods if fact["kind"] != "source_limitation"])
    section("limitations", "Limitations", [fact for fact in catalog.values() if fact["id"].startswith("limitation.")]
            + [fact for fact in methods if fact["kind"] == "source_limitation"])
    section("disclaimer", "Use of this briefing", [catalog["disclaimer"]])
    return {
        "status": status, "selected_fact_ids": selected, "highlights": highlights,
        "mandatory_context": mandatory, "rule_outcomes": outcomes,
        "measurements": detached["fusion"]["metrics"],
        "context": context, "sections": sections,
        "narrative": "\n\n".join(part["title"] + "\n" + part["text"] for part in sections),
        "source_refs": list(dict.fromkeys(ref for part in sections for ref in part["source_refs"])),
        "disclaimer": DISCLAIMER,
    }
