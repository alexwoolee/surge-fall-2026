"""Briefings remain complete, bound to evidence and safe as standalone HTML."""

from copy import deepcopy
from html.parser import HTMLParser
import json

import pytest

from backend.control.agent import build_case
from backend.control.agent_grounding import GroundingValidationError, render_explanation
from backend.control.briefing import build_briefing, render_briefing_html
from backend.control.fusion import DISCLAIMER
from test_agent_grounding import make_report
from test_contracts import hydro_result
from test_fusion import fusion_inputs, remove_flood_components


def agent_report(inputs, *, mode="review", original="Review environmental evidence for the configured historical area."):
    inputs = deepcopy(inputs)
    hydro, flood, _ = inputs
    config = {"id": "configured-case", "name": "Configured test area", "bbox": list(hydro["bbox"].values()),
              "event_start": "2021-11-14T00:00:00Z", "event_end": "2021-11-16T23:59:59Z",
              "sentinel1_smoke_start": flood["start_time"], "sentinel1_smoke_end": flood["end_time"]}
    case = build_case(config, hydro["gpm_resources"], hydro["smap_resource"], hydro["task_id"])
    inputs = (case.hydro.model_dump(mode="json"), case.flood.model_dump(mode="json"), inputs[2])
    deterministic = make_report(inputs)
    explanation = render_explanation(deterministic, None, study_area_name=case.name,
                                    execution_mode=mode, original_request=original)
    return {"mode": mode, "case": case.public_context(), "requests": deterministic["fusion"]["requests"],
            "status": "complete", "deterministic": deterministic, "explanation": explanation}


def test_complete_briefing_uses_all_measurements_rules_context_and_methods(fusion_inputs):
    report = agent_report(fusion_inputs)
    original = deepcopy(report)
    view = build_briefing(report)
    fused = report["deterministic"]["fusion"]
    assert len(view["metrics"]) == 8
    for metric, row in zip(fused["metrics"].values(), view["metrics"]):
        assert row == {"label": metric["label"], "value": f"{metric['value']!r} {metric['unit']}"}
    assert [row["status"] for row in view["reviewConditions"]] == [
        item["status"].replace("_", "-") for item in report["deterministic"]["review"]["assessments"]]
    assert len(view["sourceProvenance"]) == len(view["processingProvenance"]) == 5
    assert "WGS84" in view["studyArea"] and "-122.45" in view["studyArea"]
    assert "2021-11-14T00:00:00Z" in view["requestedWindow"]
    assert "No new worker dispatch" in view["executionNotice"]
    assert view["disclaimer"] == DISCLAIMER
    assert report == original
    body = json.dumps(view)
    for phrase in ("permanent water", "radar shadow", "Water depth", "whole-event", "not a confidence interval"):
        assert phrase.lower() in body.lower()
    assert all("unavailable" in row["duration"] for row in view["processingProvenance"])


def test_model_narrative_labels_and_raw_worker_errors_cannot_enter_briefing(fusion_inputs):
    report = agent_report(fusion_inputs)
    report["explanation"]["narrative"] = "EVACUATE, proven catastrophe 999999, SECRET-MODEL"
    report["explanation"]["sections"] = [{"title": "SECRET-TITLE", "text": "SECRET-TEXT"}]
    report["explanation"]["selected_fact_ids"] = ["invented-fact"]
    report["error"] = "SECRET-TOKEN http://100.100.3.2:8002"
    body = json.dumps(build_briefing(report))
    assert "SECRET" not in body and "EVACUATE" not in body and "100.100" not in body


@pytest.mark.parametrize("field", ["case_bbox", "case_window", "case_name", "request", "context_bbox", "context_mode", "context_name", "context_saved"])
def test_mismatched_case_task_or_saved_context_is_rejected(fusion_inputs, field):
    report = agent_report(fusion_inputs)
    if field == "case_bbox":
        report["case"]["bbox"]["west"] -= 0.1
    elif field == "case_window":
        report["case"]["requested_window"]["start"] = "2021-11-13T00:00:00Z"
    elif field == "case_name":
        report["case"]["name"] = "Different label"
    elif field == "request":
        report["requests"] = deepcopy(report["requests"])
        report["requests"][0]["gpm_resources"] = ["other.HDF5"]
    else:
        key = {"context_bbox": "bbox", "context_mode": "execution_mode", "context_name": "study_area_name",
               "context_saved": "request_retained"}[field]
        report["explanation"]["context"][key] = "MISMATCHED-SECRET"
    with pytest.raises(GroundingValidationError) as error:
        build_briefing(report)
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("mutate", ["metric", "rule", "count", "missing"])
def test_forged_metrics_and_rule_results_do_not_render(fusion_inputs, mutate):
    report = agent_report(fusion_inputs)
    if mutate == "metric":
        report["deterministic"]["fusion"]["metrics"]["hand.mean_m"]["value"] = 99
    elif mutate == "rule":
        report["deterministic"]["review"]["assessments"][0]["status"] = "triggered"
        report["deterministic"]["review"]["assessments"][0]["reason"] = "SECRET fabricated decision"
    elif mutate == "count":
        report["deterministic"]["review"]["triggered_count"] += 1
    else:
        report["deterministic"] = None
    with pytest.raises(GroundingValidationError):
        build_briefing(report)


@pytest.mark.parametrize("worker", ["hydro", "flood"])
def test_one_unavailable_worker_preserves_every_other_measurement_and_rule(fusion_inputs, worker):
    hydro, flood, combined = deepcopy(fusion_inputs)
    combined[worker] = None
    combined["errors"] = ["SECRET-INTERNAL-ERROR https://worker.test/?token=SECRET"]
    report = agent_report((hydro, flood, combined))
    view = build_briefing(report)
    assert view["partial"] is True
    expected = 4
    assert sum(row["value"].startswith("Unavailable") for row in view["metrics"]) == expected
    assert len(view["reviewConditions"]) == len(report["deterministic"]["review"]["assessments"])
    assert any(row["status"] == "not-assessable" for row in view["reviewConditions"])
    assert "SECRET" not in json.dumps(view)
    assert "zero is not substituted" in render_briefing_html(view)


def test_component_partial_does_not_hide_successful_flood_data(fusion_inputs):
    hydro, flood, combined = deepcopy(fusion_inputs)
    remove_flood_components(combined["flood"], ["hand"])
    view = build_briefing(agent_report((hydro, flood, combined)))
    assert view["partial"]
    assert sum(row["value"].startswith("Unavailable") for row in view["metrics"]) == 1
    assert "unavailable" in view["sourceProvenance"][-1]["resources"].lower()
    assert "no completed processing" in view["processingProvenance"][-1]["method"]


def test_unretained_request_is_explicit_and_degraded_explanation_remains_downloadable(fusion_inputs):
    report = agent_report(fusion_inputs, original=None)
    report["status"] = "degraded"
    report["explanation"] = None
    view = build_briefing(report)
    assert view["originalRequest"].startswith("Not retained")
    assert len(view["metrics"]) == 8
    assert "User context, not an environmental finding" in render_briefing_html(view)


def test_execute_mode_does_not_claim_new_observations_or_physical_parallelism(fusion_inputs):
    view = build_briefing(agent_report(fusion_inputs, mode="execute"))
    assert "caller-authorized" in view["executionNotice"]
    assert "does not make historical observations current" in view["executionNotice"]
    assert "not inferred" in view["executionNotice"]


@pytest.mark.parametrize("mode", ["review", "execute"])
def test_processing_duration_uses_recorded_worker_times_without_hostnames(fusion_inputs, mode):
    report = agent_report(fusion_inputs, mode=mode)
    fused = report["deterministic"]["fusion"]
    start, done = "2026-10-04T00:00:00Z", "2026-10-04T00:00:02Z"
    records = {}
    for role, task in zip(("hydro", "flood"), fused["requests"]):
        result = fused["source_results"][role]
        status = {"task_id": task["task_id"], "worker_id": result["worker_id"],
                  "analysis_type": task["analysis_type"], "state": "complete", "received_at": start,
                  "started_at": "2026-10-04T00:00:00.125000Z", "completed_at": "2026-10-04T00:00:01.375000Z",
                  "execution_host": "PRIVATE-HOSTNAME"}
        records[role] = {"task_id": task["task_id"], "worker_id": result["worker_id"],
                         "analysis_type": task["analysis_type"], "outcome": "complete",
                         "control_started_at": start, "control_completed_at": done,
                         "submitted_at": start, "accepted": True, "task_status": status,
                         "observations": [{"observed_at": done, "status": status}], "result": result}
    fused["dispatch"] = {"task_id": fused["task_id"], "execution_mode": "parallel",
                         "control_started_at": start, "control_completed_at": done,
                         **records, "combined": fused["source_results"]}
    view = build_briefing(report)
    prefix = "Retained" if mode == "review" else "Recorded"
    assert all(row["duration"].startswith(f"{prefix} execution: 1.25 seconds") for row in view["processingProvenance"])
    assert "PRIVATE-HOSTNAME" not in render_briefing_html(view)
    assert all("complete worker branch" in row["duration"] for row in view["processingProvenance"])


def test_safe_public_scene_tile_and_granule_ids_are_preserved(fusion_inputs):
    hydro, flood, combined = deepcopy(fusion_inputs)
    gpm = "3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5"
    hydro["gpm_resources"] = [gpm]
    combined["hydro"]["sources"][0]["resources_used"] = [gpm]
    combined["hydro"]["evidence"]["gpm"]["granules"][0]["file"] = gpm
    scene = "S1B_IW_GRDH_1SDV_20211115T142031_20211115T142056_029614_0388BC_rtc"
    combined["flood"]["summary"]["surface_water"]["scene_id"] = scene
    combined["flood"]["evidence"]["sentinel1"]["scene"]["scene_id"] = scene
    for component, suffix in (("dem", "DEM"), ("hand", "HAND")):
        combined["flood"]["evidence"][component]["source_tiles"][0]["tile_id"] = f"Copernicus_DSM_COG_10_N49_00_W123_00_{suffix}"
    view = build_briefing(agent_report((hydro, flood, combined)))
    resources = "\n".join(row["resources"] for row in view["sourceProvenance"])
    assert gpm in resources and scene in resources
    assert "SMAP_L4_SM_gph_20211115T013000_Vv7030_001.h5" in resources
    assert "Copernicus_DSM_COG_10_N49_00_W123_00_HAND" in resources
    assert "https://" not in resources and "file:" not in resources and "/private/" not in resources


@pytest.mark.parametrize("attack", ["https://public.test/SECRET", "/private/SECRET.tif", "<img src=x onerror=SECRET>", "Copernicus_DSM_COG_10_N49_00_W123_00_DEM?token=SECRET"])
def test_arbitrary_identifiers_and_source_urls_are_never_published(fusion_inputs, attack):
    hydro, flood, combined = deepcopy(fusion_inputs)
    for component in ("dem", "hand"):
        combined["flood"]["evidence"][component]["source_tiles"][0]["tile_id"] = attack
        combined["flood"]["evidence"][component]["source_tiles"][0]["href"] = attack
        source = next(row for row in combined["flood"]["sources"] if row["component"] == component)
        source["resources_used"] = [attack]
    view = build_briefing(agent_report((hydro, flood, combined)))
    assert "SECRET" not in json.dumps(view)
    assert "identifier unavailable" in view["sourceProvenance"][-1]["resources"]


def test_credential_bearing_source_urls_are_rejected_before_rendering(fusion_inputs):
    report = agent_report(fusion_inputs)
    report["deterministic"]["fusion"]["source_results"]["flood"]["sources"][0]["resources_used"] = ["https://public.test/scene?token=SECRET"]
    with pytest.raises(GroundingValidationError) as error:
        build_briefing(report)
    assert "SECRET" not in str(error.value)


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attributes = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


def test_standalone_html_escapes_every_dynamic_surface_without_active_content(fusion_inputs):
    attack = '</blockquote><script>alert("SECRET")</script><img src="https://evil.test" onerror="x">'
    report = agent_report(fusion_inputs, original=attack)
    view = build_briefing(report)
    original = deepcopy(view)
    # Also exercise every render-only presentation surface with hostile input.
    for key in ("title", "studyArea", "requestedWindow", "actualCoverage", "executionNotice"):
        view[key] = attack
    for key in ("metrics", "reviewConditions", "sourceProvenance", "processingProvenance"):
        for row in view[key]:
            for field in row:
                row[field] = attack
    view["sections"] = [{"id": "irrelevant", "title": attack, "paragraphs": [attack]}]
    view["limitations"] = [attack]
    html = render_briefing_html(view)
    doc = Document()
    doc.feed(html)
    assert not {"script", "img", "iframe", "a", "link", "form", "object"}.intersection(doc.tags)
    assert not any(name.startswith("on") or name in {"href", "src"} for name, value in doc.attributes)
    assert "&lt;script&gt;" in html and "&quot;SECRET&quot;" in html
    assert "Content-Security-Policy" in html and "default-src 'none'" in html
    assert "<caption>" in html and '<th scope="col">' in html
    assert "<html lang=\"en\">" in html
    # Normal generated snapshots cover every final-report requirement.
    normal = render_briefing_html(original)
    for heading in ("Original request", "Study area and time coverage", "Environmental measurements",
                    "Combined observations", "Analyst-review conditions", "Source provenance",
                    "Processing provenance", "Limitations", "Use of this briefing"):
        assert heading in normal


@pytest.mark.parametrize("mutation", [{"metrics": None}, {"partial": "false"}, {"disclaimer": "rewritten"}, {"sourceProvenance": [{"dataset": None}]}])
def test_incomplete_html_views_fail_without_echoing_data(fusion_inputs, mutation):
    view = build_briefing(agent_report(fusion_inputs))
    view.update(mutation)
    with pytest.raises(GroundingValidationError, match="incomplete or invalid"):
        render_briefing_html(view)
