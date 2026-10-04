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


def render_briefing_html(briefing: dict) -> str:
    """Render a standalone, script-free, escaped HTML snapshot of a built view.

    Only explicitly selected presentation fields can enter the document. Fixed
    headings/attributes mean source strings never become HTML, URLs or CSS.
    """
    def text(value):
        if not isinstance(value, str) or len(value) > 100_000:
            raise GroundingValidationError("The briefing contains an invalid display field.")
        return escape(value, quote=True)

    def paragraphs(values):
        if not isinstance(values, list) or len(values) > 128:
            raise GroundingValidationError("The briefing contains an invalid display section.")
        return "".join(f"<p>{text(value)}</p>" for value in values)

    def table(caption, headers, keys, rows):
        if not isinstance(rows, list) or len(rows) > 128:
            raise GroundingValidationError("The briefing contains an invalid table.")
        head = "".join(f'<th scope="col">{label}</th>' for label in headers)
        body = "".join("<tr>" + "".join(f"<td>{text(row[key])}</td>" for key in keys) + "</tr>" for row in rows)
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
        availability = ("Partial or unreported spatial coverage is present. Check the source-specific coverage below."
                        if briefing["partial"] else "Validated source results are available; temporal limitations still apply.")
        if briefing.get('risk') is not None:
            availability = 'Screening briefing prepared from the available evidence. Product availability is recorded in source notes.'
        body = f'<header><p class="eyebrow">MeshMind · Analyst support</p><h1>{title}</h1></header>'
        if briefing.get('risk') is not None:
            from backend.shared.risk_contracts import RiskView
            risk = RiskView.model_validate(briefing['risk'])
            score = 'Not assessable' if risk.score is None else f'{risk.score}/100 ordinal index'
            role = 'alert' if risk.alert else 'status'
            body += (f'<section role="{role}" aria-label="Flood-risk screening" class="risk-summary">'
                     '<h2>' + text(risk.title) + '</h2>' + paragraphs([risk.summary, risk.basis]) +
                     '<details><summary>Risk index and evidence confidence</summary><p><strong>Risk level: ' + text(risk.level) +
                     ' · ' + text(score) + '</strong></p><p>Evidence confidence: ' + text(risk.confidenceLevel) +
                     f' ({risk.confidenceScore:.3f} on a 0–1 evidence index).</p>' +
                     paragraphs(['These indices are not probabilities of flooding or dam failure.']) + '</details></section>')
        body += '<aside aria-label="Execution context">' + paragraphs([briefing.get("executionNotice", "Execution context unavailable; no new execution is established."), availability]) + '</aside>'
        body += '<section><h2>Original request</h2><p class="muted">User context, not an environmental finding.</p><blockquote>' + text(briefing["originalRequest"]) + '</blockquote></section>'
        body += '<section><h2>Study area and time coverage</h2>' + paragraphs([briefing["studyArea"], briefing["requestedWindow"], briefing["actualCoverage"]]) + '</section>'
        body += '<section><h2>Environmental measurements</h2>' + table("Validated measurements", ["Measurement", "Observed value"], ["label", "value"], briefing["metrics"]) + '</section>'
        for section in sections:
            body += '<section><h2>' + text(section["title"]) + '</h2>' + paragraphs(section["paragraphs"]) + '</section>'
        body += '<section><h2>Analyst-review conditions</h2>' + paragraphs([briefing["demoNotice"]])
        body += table("Configured demonstration conditions", ["Condition", "Observed", "Configured", "Outcome"], ["condition", "observed", "configured", "status"], briefing["reviewConditions"]) + '</section>'
        body += '<section><h2>Source provenance</h2>' + table("Source products and exact public identifiers", ["Dataset", "Access", "Resources", "Coverage"], ["dataset", "access", "resources", "coverage"], briefing["sourceProvenance"]) + '</section>'
        body += '<section><h2>Processing provenance</h2>' + table("Recorded processing", ["Investigation", "Worker role", "Method", "Processing duration"], ["investigation", "location", "method", "duration"], briefing["processingProvenance"]) + '</section>'
        body += '<section><h2>Limitations</h2>' + paragraphs(briefing["limitations"]) + '</section>'
        body += '<footer><h2>Use of this briefing</h2><p>' + text(briefing["disclaimer"]) + '</p></footer>'
    except (KeyError, TypeError, ValueError, AttributeError):
        raise GroundingValidationError("The briefing view is incomplete or invalid.") from None
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>' + title + '</title><style>' + _STYLE + '</style></head><body><main>' + body + '</main></body></html>\n'


_STYLE = """
:root{color-scheme:light;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#243340;background:#f7f8fa}
*{box-sizing:border-box}body{margin:0;line-height:1.65}main{max-width:1100px;margin:3rem auto;padding:3rem;background:#fff;border:1px solid #e1e7ed;border-radius:18px}
h1{font-size:2.4rem;line-height:1.2;font-weight:650;letter-spacing:-.04em}h2{font-size:1.35rem;line-height:1.4;margin-top:0}p{overflow-wrap:anywhere}section{margin-top:2.5rem}aside{padding:1rem 1.3rem;background:#eef4f8;border-left:4px solid #59778f;border-radius:5px}.eyebrow,.muted{color:#617387}.eyebrow{font-size:.8rem;letter-spacing:.08em;text-transform:uppercase}blockquote{margin:0;padding:1rem 1.3rem;background:#f7f8fa;border-left:3px solid #d7e0e8;white-space:pre-wrap;overflow-wrap:anywhere}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:.88rem}caption{text-align:left;color:#617387;padding:.3rem 0 .8rem}th,td{padding:.85rem;text-align:left;vertical-align:top;border-bottom:1px solid #dfe6ec;overflow-wrap:anywhere}th{background:#f1f5f8;font-weight:600}td{min-width:100px}footer{border-top:1px solid #d7e0e8;margin-top:3rem;padding-top:1.5rem;color:#425568}
@media(max-width:720px){main{margin:0;padding:1.3rem;border:0;border-radius:0}h1{font-size:2rem}}@media print{body{background:#fff}main{border:0;margin:0;padding:0;max-width:none}section,aside{break-inside:avoid}table{font-size:8pt}th,td{padding:.3rem}}
"""
