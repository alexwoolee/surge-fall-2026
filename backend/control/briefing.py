"""A deterministic presentation boundary for downloadable environmental briefings.

Worker prose, paths, URLs, model narrative and policy display labels never become
findings. Only revalidated contracts, fixed method facts and bounded, explicitly
labelled user context are presented. This is a view of evidence, not new analysis.
"""

from html import escape
import re

from backend.control.agent import build_case
from backend.control.agent_grounding import GroundingValidationError, _validated_report, render_explanation
from backend.control.alerts import DEMO_NOTICE
from backend.control.fusion import DISCLAIMER


_SOURCES = {
    "gpm": ("NASA GPM IMERG · GPM_3IMERGHH v07", "NASA Earthdata granules"),
    "smap": ("NASA SMAP L4 · SPL4SMGP v008", "NASA Earthdata state"),
    "sentinel1": ("Sentinel-1 RTC · sentinel-1-rtc", "Public RTC collection"),
    "dem": ("Copernicus DEM GLO-30 · cop-dem-glo-30", "Public terrain collection"),
    "hand": ("ASF GLO-30 HAND · glo-30-hand", "Public terrain collection"),
}
_RESOURCE_PATTERNS = {
    "gpm": re.compile(r"3B-HHR\.MS\.MRG\.3IMERG\.\d{8}-S\d{6}-E\d{6}\.\d{4}\.V\d{2}[A-Z]\.HDF5", re.ASCII),
    "smap": re.compile(r"SMAP_L4_SM_gph_\d{8}T\d{6}_Vv\d{4}_\d{3}\.h5", re.ASCII),
    "sentinel1": re.compile(r"S1[ABC]_IW_GRDH_1SD[HV]_\d{8}T\d{6}_\d{8}T\d{6}_\d{6}_[0-9A-F]{6}_rtc", re.ASCII),
    "dem": re.compile(r"Copernicus_DSM_COG_10_[NS]\d{2}_00_[EW]\d{3}_00_DEM", re.ASCII),
    "hand": re.compile(r"Copernicus_DSM_COG_10_[NS]\d{2}_00_[EW]\d{3}_00_HAND", re.ASCII),
}
_COMPARATORS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _bound_context(report, fused):
    """Bind the configured case and saved request context to the same evidence."""
    try:
        case = report["case"]
        mode = report["mode"]
        if not isinstance(case, dict) or mode not in {"review", "execute"}:
            raise ValueError
        hydro, flood = fused.requests
        rebuilt = build_case({
            "id": case["case_id"], "name": case["name"],
            "bbox": list(hydro.bbox.as_tuple()),
            "event_start": case["requested_window"]["start"],
            "event_end": case["requested_window"]["end"],
            "sentinel1_smoke_start": flood.start_time,
            "sentinel1_smoke_end": flood.end_time,
        }, hydro.gpm_resources, hydro.smap_resource, hydro.task_id)
        requests = [request.model_dump(mode="json") for request in fused.requests]
        if (case != rebuilt.public_context() or rebuilt.hydro != hydro or rebuilt.flood != flood
                or rebuilt.requested_window != fused.requested_window or report["requests"] != requests):
            raise ValueError
        explanation = report.get("explanation")
        context = explanation.get("context") if isinstance(explanation, dict) else None
        original = None
        if context is not None:
            if (not isinstance(context, dict) or context.get("bbox") != case["bbox"]
                    or context.get("study_area_name") != case["name"]
                    or context.get("execution_mode") != mode):
                raise ValueError
            original = context.get("original_request")
            if context.get("request_retained") is not (original is not None):
                raise ValueError
        return case, original, mode
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise GroundingValidationError("The briefing context does not match the validated investigation.") from None


def _resource_ids(component):
    """Publish only full, known public ID formats, never basename arbitrary URLs."""
    if component.status != "available":
        return "Unavailable; no source result was returned."
    name, evidence = component.component, component.evidence
    if name in {"gpm", "smap"}:
        values = component.provenance[0].get("resources_used", [])
    elif name == "sentinel1":
        values = [component.summary.get("scene_id")]
    else:
        values = [tile.get("tile_id") if isinstance(tile, dict) else None
                  for tile in evidence.get("source_tiles", [])]
    pattern = _RESOURCE_PATTERNS[name]
    safe = [value for value in values if isinstance(value, str) and pattern.fullmatch(value)]
    omitted = len(values) - len(safe)
    parts = list(dict.fromkeys(safe))
    if omitted or not parts:
        parts.append("Exact public identifier unavailable for one or more resources; private paths and URLs are omitted.")
    return "; ".join(parts)


def _duration(fused, worker, mode):
    if fused.dispatch is None:
        return "Worker execution duration unavailable."
    record = getattr(fused.dispatch, worker)
    status = record.task_status
    if status is None or status.started_at is None or status.completed_at is None:
        return "Worker execution duration unavailable."
    duration = (status.completed_at - status.started_at).total_seconds()
    prefix = "Retained execution" if mode == "review" else "Recorded execution"
    return f"{prefix}: {duration!r} seconds for the complete worker branch, not this individual component or observation coverage."


def build_briefing(agent_report: dict) -> dict:
    """Rebuild a complete frontend BriefingViewModel from validated observations.

    The optional original request comes only from run_agent's explicitly saved
    local context. Neither model-authored text nor a cached explanation is used
    as an authority. Invalid review/case/task binding fails closed.
    """
    if not isinstance(agent_report, dict):
        raise GroundingValidationError("A validated investigation report is required.")
    report, fused, review = _validated_report(agent_report.get("deterministic"))
    case, original, mode = _bound_context(agent_report, fused)
    rendered = render_explanation(report, None, study_area_name=case["name"],
                                  original_request=original, execution_mode=mode)
    facts = {fact["id"]: fact for fact in rendered["mandatory_context"]}
    bbox = fused.bbox.model_dump(mode="json")
    bounds = ", ".join(f"{key} {bbox[key]!r}" for key in ("west", "south", "east", "north"))
    notice = ("Review of retained evidence. No new worker dispatch or data acquisition is represented. "
              "Recorded processing durations describe the earlier investigation."
              if mode == "review" else
              "Results of the caller-authorized worker investigation. The observations retain their recorded dates; "
              "new processing does not make historical observations current. Physical parallel execution is not inferred from dispatch mode.")
    sections = []
    for section in rendered["sections"]:
        if section["id"] in {"context", "measurements", "conditions", "limitations", "disclaimer"}:
            continue
        sections.append({"id": section["id"], "title": section["title"],
                         "paragraphs": section["text"].split("\n\n")})
    conditions = []
    for index, item in enumerate(review.assessments, 1):
        metric = fused.metrics[item.metric]
        configured = f"{_COMPARATORS[item.comparator]} {item.threshold!r} {item.unit}"
        if item.required_duration_hours is not None:
            configured += f"; supplied duration {item.required_duration_hours!r} hours"
        if item.minimum_valid_fraction is not None:
            configured += f"; minimum valid fraction {item.minimum_valid_fraction!r}"
        observed = "Unavailable; zero is not substituted." if item.value is None else f"{item.value!r} {item.unit}"
        conditions.append({"id": f"condition-{index}", "condition": f"Condition {index}: {metric.label}",
                           "observed": observed + " " + item.reason, "configured": configured,
                           "status": item.status.replace("_", "-")})
    source_rows, process_rows = [], []
    for name, component in fused.components.items():
        coverage = [fact["text"] for key, fact in facts.items() if key.startswith(f"coverage.{name}.")]
        source_rows.append({"dataset": _SOURCES[name][0], "access": _SOURCES[name][1],
                            "resources": _resource_ids(component), "coverage": " ".join(coverage)})
        methods = [fact["text"] for key, fact in facts.items() if key == f"method.{name}" or key.startswith(f"method.{name}_")]
        worker = "hydro" if name in {"gpm", "smap"} else "flood"
        process_rows.append({
            "investigation": _SOURCES[name][0],
            "location": "Hydrometeorology worker" if worker == "hydro" else "Surface Water & Terrain worker",
            "method": " ".join(methods) if methods else "Component unavailable; no completed processing is claimed.",
            "duration": _duration(fused, worker, mode) if component.status == "available" else "Unavailable.",
        })
    time_ids = ["time.gpm", "time.smap", "time.sentinel1", "time.dem", "time.hand"]
    limitations = [fact["text"] for key, fact in facts.items()
                   if key.startswith("limitation.") or fact["kind"] == "source_limitation"]
    limitations.append("Public resource identifiers are shown only when they match a supported dataset format; other identifiers are unavailable in this briefing. The retained evidence report preserves original acquisition records.")
    return {
        "title": "Environmental evidence briefing",
        "originalRequest": original if original is not None else "Not retained; original request saving was not enabled.",
        "studyArea": f"{case['name']} (configured label). WGS84 bounds in degrees: {bounds}.",
        "requestedWindow": facts["time.requested"]["text"],
        "actualCoverage": " ".join(facts[key]["text"] for key in time_ids),
        "executionNotice": notice,
        "partial": fused.status != "complete" or any(
            metric.status != "available" or metric.valid_fraction is None or metric.valid_fraction < 1
            for metric in fused.metrics.values()),
        "sections": sections,
        "metrics": [{"label": metric.label,
                     "value": f"{metric.value!r} {metric.unit}" if metric.status == "available"
                     else "Unavailable; zero is not substituted."} for metric in fused.metrics.values()],
        "reviewConditions": conditions, "sourceProvenance": source_rows,
        "processingProvenance": process_rows, "limitations": limitations,
        "disclaimer": DISCLAIMER, "demoNotice": DEMO_NOTICE,
    }


_ABSENT_DISPLAY_VALUES = frozenset({
    "Unavailable.", "Unavailable", "Unavailable; zero is not substituted.",
    "Unavailable; no source result was returned.", "Not returned", "Not available",
})
_ROUTINE_SOURCE_NOTES = frozenset({
    "The requested period predates this product.",
    "The catalog returned no eligible observations for the requested area and interval.",
    "Terrain excluded because its observation date cannot be verified against the historical cutoff.",
})


def _present_risk_text(value, level):
    if level == "unknown":
        return value
    sentences = re.split(r"(?<=[.!?])\s+", value)
    retained = [sentence for sentence in sentences if sentence !=
                "DEM and HAND are unavailable, so local topographic screening cannot be applied here."]
    return " ".join(retained) if retained else value


def _briefing_presentation(briefing):
    """Project display rows without changing saved evidence or availability."""
    for key in ("metrics", "reviewConditions", "sourceProvenance"):
        if not isinstance(briefing[key], list) or len(briefing[key]) > 128:
            raise ValueError
    sources = [{**row, "coverage": row["coverage"].replace("Only part of the requested rainfall interval is available.", "").strip()}
               for row in briefing["sourceProvenance"] if row["resources"] not in _ABSENT_DISPLAY_VALUES]
    operational = [row for row in briefing["sourceProvenance"]
                   if row["resources"] in _ABSENT_DISPLAY_VALUES and row["coverage"] not in _ROUTINE_SOURCE_NOTES]
    return {
        "metrics": [row for row in briefing["metrics"] if row["value"] not in _ABSENT_DISPLAY_VALUES],
        "conditions": [row for row in briefing["reviewConditions"] if row["status"] != "not-assessable"],
        "sources": sources, "operational": operational,
        "limitations": [text for text in briefing["limitations"] if text != "Missing evidence stays unavailable. It is not treated as zero or evidence of safety."],
        "coverage": " ".join(f"{row['dataset']}: {row['coverage']}" for row in sources),
    }


def render_briefing_html(briefing: dict) -> str:
    """Render a standalone, script-free, escaped HTML snapshot of a built view.

    Only explicitly selected presentation fields can enter the document. Fixed
    headings/attributes mean source strings never become HTML, URLs or CSS.
    """
    def text(value, *, branded=True):
        if not isinstance(value, str) or len(value) > 100_000:
            raise GroundingValidationError("The briefing contains an invalid display field.")
        return escape(value.replace("MeshMind", "Amalga") if branded else value, quote=True)

    def paragraphs(values):
        if not isinstance(values, list) or len(values) > 128:
            raise GroundingValidationError("The briefing contains an invalid display section.")
        return "".join(f"<p>{text(value)}</p>" for value in values)

    def table(caption, headers, keys, rows):
        if not isinstance(rows, list) or len(rows) > 128:
            raise GroundingValidationError("The briefing contains an invalid table.")
        head = "".join(f'<th scope="col">{label}</th>' for label in headers)
        body = "".join("<tr>" + "".join(f"<td>{text(row[key], branded=key != "resources")}</td>" for key in keys) + "</tr>" for row in rows)
        return f'<div class="table-wrap"><table><caption>{caption}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    try:
        if not isinstance(briefing, dict) or type(briefing["partial"]) is not bool:
            raise ValueError
        if briefing["disclaimer"] != DISCLAIMER or briefing["demoNotice"] != DEMO_NOTICE:
            raise ValueError
        sections = briefing["sections"]
        if not isinstance(sections, list) or len(sections) > 32:
            raise ValueError
        title = text(briefing["title"])
        display = _briefing_presentation(briefing)
        availability = ('Screening briefing prepared from the available evidence.' if briefing.get('risk') is not None
                        else 'Evidence briefing prepared from validated source results.')
        body = f'<header><p class="eyebrow">Amalga · Analyst support</p><h1>{title}</h1></header>'
        if briefing.get('risk') is not None:
            from backend.shared.risk_contracts import RiskView
            risk = RiskView.model_validate(briefing['risk'])
            score = 'Not assessable' if risk.score is None else f'{risk.score}/100 ordinal index'
            role = 'alert' if risk.alert else 'status'
            body += (f'<section role="{role}" aria-label="Flood-risk screening" class="risk-summary risk-{risk.level}">'
                     '<p class="eyebrow">' + text('Risk not assessable' if risk.level == 'unknown' else risk.level.title() + ' risk') + '</p>' +
                     '<h2>' + text(risk.title) + '</h2>' + paragraphs([_present_risk_text(risk.summary, risk.level), _present_risk_text(risk.basis, risk.level)]) +
                     '<details><summary>Risk index and evidence confidence</summary><p><strong>Risk level: ' + text(risk.level) +
                     ' · ' + text(score) + '</strong></p><p>Evidence confidence: ' + text(risk.confidenceLevel) +
                     f' ({risk.confidenceScore:.3f} on a 0–1 evidence index).</p>' +
                     paragraphs(['These indices are not probabilities of flooding or dam failure.']) + '</details></section>')
        body += '<aside aria-label="Execution context">' + paragraphs([briefing.get("executionNotice", "Execution context unavailable; no new execution is established."), availability]) + '</aside>'
        body += '<section><h2>Original request</h2><p class="muted">User context, not an environmental finding.</p><blockquote>' + text(briefing["originalRequest"], branded=False) + '</blockquote></section>'
        body += '<section><h2>Study area and time coverage</h2>' + paragraphs([briefing["studyArea"], briefing["requestedWindow"], display["coverage"]]) + '</section>'
        body += '<section><h2>Environmental measurements</h2>' + table("Validated measurements", ["Measurement", "Observed value"], ["label", "value"], display["metrics"]) + '</section>'
        for section in sections:
            if briefing.get('risk') is not None and section["id"] == "risk":
                continue
            body += '<section><h2>' + text(section["title"]) + '</h2>' + paragraphs(section["paragraphs"]) + '</section>'
        if display["conditions"]:
            body += '<section><h2>Analyst-review conditions</h2>' + paragraphs([briefing["demoNotice"].replace("MeshMind", "Amalga")])
            body += table("Assessable configured conditions", ["Condition", "Observed", "Configured", "Outcome"], ["condition", "observed", "configured", "status"], display["conditions"]) + '</section>'
        body += '<details class="technical"><summary>Sources, processing and technical notes</summary>'
        body += '<section><h2>Source provenance</h2>' + table("Source products and exact public identifiers", ["Dataset", "Access", "Resources", "Coverage"], ["dataset", "access", "resources", "coverage"], display["sources"]) + '</section>'
        if display["operational"]:
            body += '<section><h2>Operational notes</h2>' + paragraphs([f"{row['dataset']}: {row['coverage']}" for row in display["operational"]]) + '</section>'
        body += '<section><h2>Processing provenance</h2>' + table("Recorded processing", ["Investigation", "Worker role", "Method", "Processing duration"], ["investigation", "location", "method", "duration"], briefing["processingProvenance"]) + '</section>'
        body += '<section><h2>Limitations</h2>' + paragraphs(display["limitations"]) + '</section>'
        body += '<p class="muted">Only measured values and assessable conditions are listed. For other values, zero is not substituted; retained evidence preserves all availability and rule outcomes.</p></details>'
        body += '<footer><h2>Use of this briefing</h2><p>' + text(briefing["disclaimer"].replace("MeshMind", "Amalga")) + '</p></footer>'
    except (KeyError, TypeError, ValueError, AttributeError):
        raise GroundingValidationError("The briefing view is incomplete or invalid.") from None
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>' + title + '</title><style>' + _STYLE + '</style></head><body><main>' + body + '</main></body></html>\n'


_STYLE = """
:root{color-scheme:dark;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f4f2ef;background:#0c0b0a}
*{box-sizing:border-box}body{margin:0;line-height:1.65}main{max-width:960px;margin:3rem auto;padding:2.5rem;background:#151413;border:1px solid #34312e;border-radius:22px}
h1{font-size:2.3rem;line-height:1.2;font-weight:550;letter-spacing:-.04em}h2{font-size:1.2rem;line-height:1.4;margin-top:0}p{overflow-wrap:anywhere}section{margin-top:2.2rem}aside{padding:1rem 1.2rem;background:#1b1a18;border:1px solid #34312e;border-radius:12px;font-size:.88rem;color:#a39e98}.eyebrow,.muted{color:#a39e98}.eyebrow{font-size:.75rem;letter-spacing:.1em;text-transform:uppercase}blockquote{margin:0;padding:1rem 1.2rem;background:#1b1a18;border-left:2px solid #78736d;white-space:pre-wrap;overflow-wrap:anywhere}
.risk-summary{padding:1.4rem;background:#1b1a18;border:1px solid #46423d;border-radius:14px;margin-bottom:1.8rem}.risk-high,.risk-critical{border-color:#be7045}.risk-high>.eyebrow,.risk-critical>.eyebrow{color:#ffc091}details{margin-top:1.2rem}summary{cursor:pointer;color:#d4cfc9;font-weight:550}.technical{margin-top:2rem;border-top:1px solid #34312e;padding-top:1.4rem}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:.85rem}caption{text-align:left;color:#a39e98;padding:.3rem 0 .8rem}th,td{padding:.8rem;text-align:left;vertical-align:top;border-bottom:1px solid #34312e;overflow-wrap:anywhere}th{background:#1b1a18;font-weight:550;color:#d4cfc9}td{min-width:100px}footer{border-top:1px solid #34312e;margin-top:2.5rem;padding-top:1.5rem;color:#a39e98;font-size:.88rem}
@media(max-width:720px){main{margin:0;padding:1.3rem;border:0;border-radius:0}h1{font-size:1.8rem}}@media print{:root,body,main,aside,blockquote,th,.risk-summary{color:#222;background:#fff}main{border:0;margin:0;padding:0;max-width:none}.eyebrow,.muted,caption,footer,summary{color:#444}section,aside{break-inside:avoid}details> :not(summary){display:block}table{font-size:8pt}th,td{padding:.3rem}}
"""
