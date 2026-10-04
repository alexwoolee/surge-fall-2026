"""Contracts round-trip actual processor outputs and reject inconsistent inputs."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import numpy as np
from pydantic import ValidationError
import pytest

from backend.shared.contracts import (
    AnalysisTask, BoundingBox, CombinedAnalysis, Coverage, FloodResult,
    HydroResult, TaskStatus, WorkerStatus,
)
from backend.shared.status import TaskState, TERMINAL_STATES
from backend.workers.flood.service import run_flood_analysis
from backend.workers.hydro.service import run_hydro_analysis
from test_flood import resources as flood_resources
from test_hydro import create_gpm_file
from test_smap import create_smap_file


BBOX = {"west": -122.45, "south": 48.95, "east": -121.95, "north": 49.30}
HYDRO_TASK = {"analysis_type": "hydrometeorology", "bbox": BBOX,
              "gpm_resources": ["gpm.HDF5"], "smap_resource": "smap.h5"}
FLOOD_TASK = {"analysis_type": "surface_water_and_terrain", "bbox": BBOX,
              "start_time": "2021-11-13T00:00:00Z", "end_time": "2021-11-18T23:59:59Z"}


@pytest.fixture
def hydro_result(tmp_path):
    """Real deterministic Hydro output from small HDF5 files."""
    gpm = create_gpm_file(tmp_path / "gpm.HDF5", np.ones((4, 3), dtype="float32"))
    smap = create_smap_file(tmp_path / "SMAP_L4_SM_gph_20211115T013000_Vv7030_001.h5",
                            np.full((3, 3), 0.4), np.full((3, 3), 0.3))
    return run_hydro_analysis([gpm], smap, tuple(BBOX.values()), task_id="contract-task")


@pytest.fixture
def flood_result(flood_resources):
    """Real deterministic Flood output from small calibrated rasters."""
    return run_flood_analysis(**flood_resources, task_id="contract-task")


def test_tasks_roundtrip_and_have_unique_generated_ids():
    for raw in (HYDRO_TASK, FLOOD_TASK):
        model = AnalysisTask.model_validate(raw)
        assert AnalysisTask.model_validate_json(model.model_dump_json()) == model
        assert model.bbox.as_tuple() == tuple(BBOX.values())
        assert model.task_id != AnalysisTask.model_validate(raw).task_id
    aware = AnalysisTask.model_validate({**FLOOD_TASK, "reference_time": "2021-11-15T10:00:00-08:00"})
    assert aware.reference_time.utcoffset() == timedelta(hours=-8)


@pytest.mark.parametrize("update", [
    {"task_id": "../bad"}, {"task_id": ""}, {"task_id": "x" * 129}, {"task_id": True},
    {"task_id": "with spaces"}, {"analysis_type": "unsupported"}, {"extra": 1},
    {"gpm_resources": []}, {"gpm_resources": ["../data.h5"]},
    {"gpm_resources": ["https://example.test/gpm.h5"]},
    {"gpm_resources": ["a.h5", "a.h5"]}, {"gpm_resources": ["x..h5"]},
    {"gpm_resources": [f"{i}.h5" for i in range(49)]},
    {"gpm_resources": "gpm.h5"}, {"gpm_resources": [1]},
    {"smap_resource": "/cache/smap.h5"}, {"smap_resource": "C:\\smap.h5"},
    {"smap_resource": None}, {"threshold_db": -19},
    {"start_time": "2021-11-13T00:00:00Z"},
])
def test_hydro_task_rejects_unbounded_or_wrong_inputs(update):
    with pytest.raises(ValidationError):
        AnalysisTask.model_validate({**HYDRO_TASK, **update})


@pytest.mark.parametrize("update", [
    {"start_time": None}, {"end_time": None}, {"start_time": "2021-11-13"},
    {"start_time": "2021-11-13T00:00:00"}, {"start_time": 1636761600},
    {"end_time": "2021-11-13T00:00:00Z"}, {"end_time": "2021-11-12T00:00:00Z"},
    {"end_time": "2021-11-20T00:00:01Z"}, {"reference_time": "2021-11-12T00:00:00Z"},
    {"gpm_resources": ["gpm.h5"]}, {"smap_resource": "smap.h5"},
    {"threshold_db": float("nan")}, {"threshold_db": float("inf")},
    {"threshold_db": -41}, {"threshold_db": 1}, {"threshold_db": True},
    {"threshold_db": "-17"},
])
def test_flood_task_rejects_unbounded_or_wrong_inputs(update):
    with pytest.raises(ValidationError):
        AnalysisTask.model_validate({**FLOOD_TASK, **update})


@pytest.mark.parametrize("bounds", [
    {**BBOX, "west": "-122.45"}, {**BBOX, "west": True},
    {**BBOX, "west": float("nan")}, {**BBOX, "south": -91},
    {**BBOX, "east": 181}, {**BBOX, "east": BBOX["west"]},
    {**BBOX, "south": BBOX["north"]}, {**BBOX, "west": 179, "east": -179},
])
def test_bbox_rejects_invalid_geometry_or_types(bounds):
    with pytest.raises(ValidationError):
        BoundingBox.model_validate(bounds)


def test_task_bbox_is_bounded_but_result_geometry_can_be_larger():
    bounds = {"west": 0, "south": 0, "east": 3, "north": 1}
    assert BoundingBox.model_validate(bounds).east == 3
    with pytest.raises(ValidationError):
        AnalysisTask.model_validate({**HYDRO_TASK, "bbox": bounds})
    assert AnalysisTask.model_validate({**FLOOD_TASK, "end_time": "2021-11-20T00:00:00Z"})


def test_actual_hydro_result_roundtrip_preserves_all_evidence(hydro_result):
    model = HydroResult.model_validate(hydro_result)
    assert model.evidence == hydro_result["evidence"]
    assert HydroResult.model_validate_json(model.model_dump_json()) == model
    assert json.loads(model.model_dump_json())["summary"] == hydro_result["summary"]


def test_actual_flood_result_roundtrip_preserves_all_evidence(flood_result):
    model = FloodResult.model_validate(flood_result)
    assert model.evidence == flood_result["evidence"]
    assert FloodResult.model_validate_json(model.model_dump_json()) == model
    assert model.model_dump(mode="json") == flood_result
    # Partial coverage does not change the component-success status.
    assert model.status == "complete"


@pytest.mark.parametrize("remove", [{"dem"}, {"sentinel1", "hand"}, {"sentinel1", "dem", "hand"}])
def test_partial_and_failed_flood_results_omit_missing_summaries(flood_result, remove):
    result = deepcopy(flood_result)
    keys = {"sentinel1": "surface_water", "dem": "elevation", "hand": "hand"}
    for component in remove:
        result["evidence"].pop(component)
        result["coverage"].pop(component)
        result["summary"].pop(keys[component])
        result["sources"] = [source for source in result["sources"] if source["component"] != component]
        result["errors"].append({"component": component, "code": "processing_failed", "message": "Source unavailable."})
    result["status"] = "failed" if len(remove) == 3 else "partial"
    model = FloodResult.model_validate(result)
    assert model.model_dump(mode="json") == result
    assert FloodResult.model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("path,value", [
    (("summary", "rainfall", "area_mean_total_accumulation_mm"), 99),
    (("summary", "rainfall", "granule_count"), True),
    (("summary", "soil_moisture", "surface_mean_m3_m3"), 0.8),
    (("summary", "soil_moisture", "smap_timestamp_utc"), "2021-11-14T00:00:00Z"),
    (("evidence", "gpm", "rainfall", "area_mean_total_accumulation_mm"), float("inf")),
    (("evidence", "smap", "bbox", "west"), -122.4),
    (("evidence", "gpm", "deep_extra"), {"nested": [float("nan")]}),
    (("sources", 0, "resources_used"), ["https://example.test/a?token=hidden"]),
    (("status",), "partial"), (("worker_id",), "flood-worker"),
])
def test_hydro_rejects_inconsistent_or_unsafe_result(hydro_result, path, value):
    data = deepcopy(hydro_result)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        HydroResult.model_validate(data)


@pytest.mark.parametrize("path,value", [
    (("status",), "partial"), (("worker_id",), "hydro-worker"),
    (("summary", "surface_water", "candidate_area_km2"), 10),
    (("summary", "elevation", "valid_pixels"), True),
    (("summary", "elevation", "mean_m"), float("nan")),
    (("summary", "hand", "min_m"), -1),
    (("coverage", "dem", "valid_fraction"), 0.5),
    (("coverage", "sentinel1", "status"), "partial"),
    (("evidence", "sentinel1", "scene", "href"), "https://user:secret@example.test/raster"),
    (("evidence", "sentinel1", "scene", "href"), "https://example.test/raster?sig=hidden"),
    (("evidence", "dem", "metadata"), [float("nan")]),
    (("evidence", "hand", "bbox"), [0, 0, 1, 1]),
    (("evidence", "sentinel1", "candidate_water", "count"), -1),
    (("errors",), [{"component": "dem", "code": "processing_failed", "message": "Unavailable."}]),
    (("sources",), []),
])
def test_flood_rejects_inconsistent_or_unsafe_result(flood_result, path, value):
    data = deepcopy(flood_result)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        FloodResult.model_validate(data)


def test_missing_component_evidence_is_not_zero_measurement(hydro_result, flood_result):
    del hydro_result["evidence"]["smap"]
    with pytest.raises(ValidationError):
        HydroResult.model_validate(hydro_result)
    del flood_result["evidence"]["dem"]
    with pytest.raises(ValidationError):
        FloodResult.model_validate(flood_result)


def test_worker_and_task_status_roundtrip():
    now = datetime.now(timezone.utc)
    worker = WorkerStatus(worker_id="hydro-worker", analysis_type="hydrometeorology",
                          status="busy", active_task_id="test", retained_tasks=1, capacity=8)
    assert WorkerStatus.model_validate_json(worker.model_dump_json()) == worker
    for state in TaskState:
        status = TaskStatus(task_id="test", worker_id="hydro-worker", analysis_type="hydrometeorology",
                            state=state, received_at=now, started_at=now,
                            completed_at=now if state in TERMINAL_STATES else None)
        assert TaskStatus.model_validate_json(status.model_dump_json()) == status


@pytest.mark.parametrize("changes", [
    {"started_at": None}, {"completed_at": None},
    {"started_at": "2021-11-14T00:00:00Z"},
    {"completed_at": "2021-11-14T00:00:00Z"},
    {"received_at": "2021-11-15T00:00:00"},
    {"error": "Unexpected error"}, {"analysis_type": "surface_water_and_terrain"},
])
def test_task_status_requires_consistent_identity_and_timing(changes):
    now = "2021-11-15T00:00:00Z"
    raw = dict(task_id="test", worker_id="hydro-worker", analysis_type="hydrometeorology",
               state="complete", received_at=now, started_at=now, completed_at=now)
    with pytest.raises(ValidationError):
        TaskStatus.model_validate({**raw, **changes})


@pytest.mark.parametrize("changes", [
    {"status": "busy"}, {"active_task_id": "unexpected"},
    {"retained_tasks": 9}, {"capacity": 0}, {"retained_tasks": True},
    {"analysis_type": "surface_water_and_terrain"},
])
def test_worker_status_rejects_impossible_state(changes):
    raw = dict(worker_id="hydro-worker", analysis_type="hydrometeorology", status="idle",
               retained_tasks=0, capacity=8)
    with pytest.raises(ValidationError):
        WorkerStatus.model_validate({**raw, **changes})


def test_combined_analysis_keeps_independent_result_and_explicit_error(hydro_result):
    combined = CombinedAnalysis(task_id=hydro_result["task_id"], hydro=hydro_result,
                                errors=["Flood worker unavailable."])
    assert CombinedAnalysis.model_validate_json(combined.model_dump_json()) == combined
    assert combined.hydro.summary.rainfall.granule_count == 1
    assert combined.flood is None
    with pytest.raises(ValidationError):
        CombinedAnalysis(task_id="other-task", hydro=hydro_result)
    with pytest.raises(ValidationError):
        CombinedAnalysis(task_id="empty")
    assert CombinedAnalysis(task_id="error-only", errors=["Workers unavailable."])
