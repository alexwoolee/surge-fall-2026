"""Evidence assembly preserves measured inputs and rejects incompatible claims."""

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from backend.control.fusion import (
    DISCLAIMER, METRIC_UNITS, FusionResult, FusionValidationError, fuse_analysis,
)
from backend.control.state import DispatchRun
from backend.shared.contracts import AnalysisTask, CombinedAnalysis, HydroResult
from backend.workers.flood._raster import RasterTile
from backend.workers.flood.hand import HAND_COLLECTION
from backend.workers.flood.sentinel1 import Sentinel1Scene
from backend.workers.flood.service import run_flood_analysis
from backend.workers.flood.terrain import DEM_COLLECTION
from test_contracts import hydro_result
from test_flood import write_raster


def make_fusion_inputs(hydro_result, flood_result=None):
    """Create request context for coherent fixtures, preserving their actual AOI."""
    result = hydro_result if hydro_result is not None else flood_result
    task_id, bbox = result["task_id"], result["bbox"]
    hydro = {
        "task_id": task_id, "analysis_type": "hydrometeorology", "bbox": bbox,
        "gpm_resources": hydro_result["sources"][0]["resources_used"] if hydro_result else ["missing.HDF5"],
        "smap_resource": hydro_result["sources"][1]["resources_used"][0] if hydro_result else "missing.h5",
    }
    flood = {
        "task_id": task_id, "analysis_type": "surface_water_and_terrain", "bbox": bbox,
        "start_time": "2021-11-13T00:00:00Z", "end_time": "2021-11-18T23:59:59Z",
        "threshold_db": -17.0,
    }
    return deepcopy(hydro), deepcopy(flood), deepcopy({
        "task_id": task_id, "hydro": hydro_result, "flood": flood_result,
        "errors": [] if hydro_result is not None and flood_result is not None else ["One worker result is unavailable."],
    })


@pytest.fixture
def fusion_inputs(tmp_path, hydro_result):
    """Actual small processors on matching AOI, with independent native grids."""
    bbox = tuple(hydro_result["bbox"][key] for key in ("west", "south", "east", "north"))
    projected = transform_bounds("EPSG:4326", "EPSG:32610", *bbox)
    sar_path = tmp_path / "fusion-sar.tif"
    write_raster(sar_path, [[0.01, 0.1], [1, 0.001]], from_bounds(*projected, 2, 2), "EPSG:32610")
    dem_path, hand_path = tmp_path / "fusion-dem.tif", tmp_path / "fusion-hand.tif"
    write_raster(dem_path, [[-2, 0, 10], [20, 30, 40]], from_bounds(*bbox, 3, 2), "EPSG:4326")
    write_raster(hand_path, [[0, 1], [4, 8]], from_bounds(*bbox, 2, 2), "EPSG:4326")
    flood = run_flood_analysis(
        Sentinel1Scene("fusion-scene", str(sar_path), "2021-11-15T14:00:00Z", bbox),
        [RasterTile("fusion-dem", str(dem_path), DEM_COLLECTION)],
        [RasterTile("fusion-hand", str(hand_path), HAND_COLLECTION)], bbox,
        task_id=hydro_result["task_id"],
    )
    assert flood["status"] == "complete"
    return make_fusion_inputs(hydro_result, flood)


def test_complete_fusion_is_lossless_deterministic_and_has_explicit_temporal_limits(fusion_inputs):
    original = deepcopy(fusion_inputs)
    window = {"start": "2021-11-14T16:00:00-08:00", "end": "2021-11-15T16:00:00-08:00"}
    result = fuse_analysis(*fusion_inputs, requested_window=window)
    assert result.status == "complete" and result.disclaimer == DISCLAIMER
    assert set(result.metrics) == set(METRIC_UNITS) and len(result.components) == 5
    assert all(item.status == "available" for item in result.metrics.values())
    assert result.source_results.model_dump(mode="json") == CombinedAnalysis.model_validate(original[2]).model_dump(mode="json")
    assert fusion_inputs == original
    assert result.model_dump_json() == fuse_analysis(*fusion_inputs, requested_window=window).model_dump_json()
    assert json.loads(json.dumps(result.model_dump(mode="json"), allow_nan=False))
    assert FusionResult.model_validate_json(result.model_dump_json()) == result
    assert result.requested_window.start == datetime(2021, 11, 15, tzinfo=timezone.utc)
    rain_time = result.components["gpm"].time_basis
    assert rain_time["duration_hours"] == 0.5
    assert rain_time["interval_start"] is None and rain_time["interval_end"] is None
    assert rain_time["continuity"] == "unknown"
    assert result.components["smap"].time_basis["observed_at"] == "2021-11-15T01:30:00Z"
    assert result.components["sentinel1"].time_basis["observed_at"] == "2021-11-15T14:00:00Z"
    assert result.components["hand"].time_basis["observed_at"] is None


@pytest.mark.parametrize("field", ["task_id", "bbox"])
def test_request_or_result_identity_mismatch_is_rejected(fusion_inputs, field):
    hydro, flood, combined = fusion_inputs
    if field == "task_id":
        flood[field] = "different-task"
    else:
        flood["bbox"]["west"] += 0.01
    with pytest.raises(FusionValidationError, match="task ID and AOI"):
        fuse_analysis(hydro, flood, combined)


def test_wrong_roles_and_returned_aoi_are_rejected(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    with pytest.raises(FusionValidationError, match="roles"):
        fuse_analysis(flood, hydro, combined)
    for task in (hydro, flood):
        task["bbox"]["west"] += 0.01
    with pytest.raises(FusionValidationError, match="requested task ID and AOI"):
        fuse_analysis(hydro, flood, combined)


@pytest.mark.parametrize("resource", ["gpm", "smap", "gpm_evidence", "smap_evidence"])
def test_request_resources_and_detailed_provenance_must_agree(fusion_inputs, resource):
    hydro, flood, combined = fusion_inputs
    if resource == "gpm":
        hydro["gpm_resources"] = ["different.HDF5"]
    elif resource == "smap":
        hydro["smap_resource"] = "different.h5"
    elif resource == "gpm_evidence":
        combined["hydro"]["evidence"]["gpm"]["granules"][0]["file"] = "different.HDF5"
    else:
        combined["hydro"]["evidence"]["smap"]["file"] = "different.h5"
    with pytest.raises(FusionValidationError):
        fuse_analysis(hydro, flood, combined)


@pytest.mark.parametrize("change", ["time", "threshold"])
def test_sentinel_scene_must_match_requested_search_and_threshold(fusion_inputs, change):
    hydro, flood, combined = fusion_inputs
    if change == "time":
        flood.update(start_time="2021-11-16T00:00:00Z", end_time="2021-11-17T00:00:00Z")
    else:
        flood["threshold_db"] = -18
    with pytest.raises(FusionValidationError, match="search window and threshold"):
        fuse_analysis(hydro, flood, combined)


def remove_flood_components(result, removed):
    keys = {"sentinel1": "surface_water", "dem": "elevation", "hand": "hand"}
    for component in removed:
        result["evidence"].pop(component)
        result["coverage"].pop(component)
        result["summary"].pop(keys[component])
        result["sources"] = [source for source in result["sources"] if source["component"] != component]
        result["errors"].append({"component": component, "code": "processing_failed", "message": "Source unavailable."})
    result["status"] = "failed" if len(removed) == 3 else "partial"


@pytest.mark.parametrize("missing", ["hydro", "flood"])
def test_one_missing_worker_preserves_other_measurements(fusion_inputs, missing):
    hydro, flood, combined = fusion_inputs
    combined[missing] = None
    combined["errors"] = [f"{missing}-worker: transport unavailable."]
    result = fuse_analysis(hydro, flood, combined)
    assert result.status == "partial"
    retained = "flood" if missing == "hydro" else "hydro"
    assert getattr(result.source_results, retained) is not None
    for metric in result.metrics.values():
        absent = (metric.component in {"gpm", "smap"}) == (missing == "hydro")
        assert (metric.status == "unavailable") is absent
        assert (metric.value is None) is absent
        if absent:
            assert metric.unavailable_reason and metric.valid_fraction is None


@pytest.mark.parametrize("removed", [{"dem"}, {"sentinel1", "hand"}, {"sentinel1", "dem", "hand"}])
def test_partial_and_failed_flood_keep_successful_components(fusion_inputs, removed):
    hydro, flood, combined = fusion_inputs
    original_hydro = deepcopy(combined["hydro"])
    remove_flood_components(combined["flood"], removed)
    result = fuse_analysis(hydro, flood, combined)
    assert result.status == "partial"
    assert result.source_results.hydro.model_dump(mode="json") == HydroResult.model_validate(original_hydro).model_dump(mode="json")
    for component in ("sentinel1", "dem", "hand"):
        item = result.components[component]
        assert (item.status == "unavailable") == (component in removed)
        if component in removed:
            assert item.errors[0]["code"] == "processing_failed"
            assert item.evidence is None


def test_all_missing_has_no_numbers_and_preserves_errors(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    combined.update(hydro=None, flood=None, errors=["Hydro timed out.", "Flood rejected the task."])
    result = fuse_analysis(hydro, flood, combined)
    assert result.status == "unavailable"
    assert all(metric.value is None and metric.unavailable_reason for metric in result.metrics.values())
    assert result.source_results.errors == combined["errors"]


def test_partial_spatial_coverage_does_not_become_missing_processing(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    result = combined["flood"]
    coverage = result["coverage"]["sentinel1"]
    coverage["aoi_pixels"] *= 2
    coverage["coverage_fraction"] = coverage["covered_pixels"] / coverage["aoi_pixels"]
    coverage["valid_fraction"] = coverage["valid_pixels"] / coverage["aoi_pixels"]
    coverage["status"] = "partial"
    result["evidence"]["sentinel1"]["coverage"] = deepcopy(coverage)
    result["summary"]["surface_water"]["valid_fraction"] = coverage["valid_fraction"]
    fused = fuse_analysis(hydro, flood, combined)
    assert fused.status == "complete"
    assert fused.components["sentinel1"].status == "available"
    assert fused.components["sentinel1"].coverage["status"] == "partial"
    assert fused.metrics["sentinel1.candidate_area_km2"].valid_fraction == coverage["valid_fraction"]


def test_unreported_hydro_coverage_stays_unknown_without_removing_values(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    combined["hydro"]["evidence"]["gpm"].pop("selected_grid")
    combined["hydro"]["evidence"]["smap"]["surface_soil_moisture"].pop("valid_pixels")
    result = fuse_analysis(hydro, flood, combined)
    for name in ("gpm.mean_accumulation_mm", "smap.surface_mean_m3_m3"):
        assert result.metrics[name].value is not None
        assert result.metrics[name].valid_fraction is None
    assert result.metrics["smap.rootzone_mean_m3_m3"].valid_fraction is not None
    assert any("unreported" in note for note in result.components["gpm"].limitations)


def test_explicit_null_granules_preserve_measurements_with_unknown_coverage(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    measured = combined["hydro"]["summary"]["rainfall"]["area_mean_total_accumulation_mm"]
    combined["hydro"]["evidence"]["gpm"]["granules"] = None
    result = fuse_analysis(hydro, flood, combined)
    metric = result.metrics["gpm.mean_accumulation_mm"]
    assert metric.value == measured and metric.status == "available"
    assert metric.valid_fraction is None
    assert any("per-granule support is unreported" in note for note in result.components["gpm"].limitations)
    assert result.source_results.hydro.evidence["gpm"]["granules"] is None


@pytest.mark.parametrize("component,field,value", [
    ("gpm_grid", "complete_coverage_fraction", 0.01),
    ("gpm_grid", "total_pixels", True),
    ("gpm_grid", "complete_coverage_pixels", 100000),
    ("gpm_grid", "longitude_cells", 100000),
    ("gpm", "duration_hours_per_granule", 3),
    ("gpm_granule", "valid_pixels", 100000),
    ("smap_grid", "aoi_pixels", 0),
    ("smap_grid", "aoi_pixels", 100000),
    ("smap_grid", "window_rows", 100000),
    ("smap_surface", "valid_pixels", 100000),
    ("smap_surface", "units", "kg"),
    ("smap_surface", "units", []),
])
def test_corrupt_eligibility_metadata_is_rejected(fusion_inputs, component, field, value):
    hydro, flood, combined = fusion_inputs
    evidence = combined["hydro"]["evidence"]
    targets = {"gpm_grid": evidence["gpm"]["selected_grid"], "gpm": evidence["gpm"],
               "gpm_granule": evidence["gpm"]["granules"][0],
               "smap_grid": evidence["smap"]["selected_grid"],
               "smap_surface": evidence["smap"]["surface_soil_moisture"]}
    targets[component][field] = value
    with pytest.raises(FusionValidationError):
        fuse_analysis(hydro, flood, combined)


def test_detached_revalidation_rejects_mutated_model_and_result_has_no_input_alias(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    model = CombinedAnalysis.model_validate(combined)
    model.hydro.summary.rainfall.area_mean_total_accumulation_mm = 999
    with pytest.raises(FusionValidationError):
        fuse_analysis(AnalysisTask.model_validate(hydro), AnalysisTask.model_validate(flood), model)
    result = fuse_analysis(hydro, flood, combined)
    combined["hydro"]["summary"]["rainfall"]["area_mean_total_accumulation_mm"] = 777
    assert result.metrics["gpm.mean_accumulation_mm"].value != 777
    result.metrics["gpm.mean_accumulation_mm"].value = 888
    with pytest.raises(ValueError, match="grounded"):
        FusionResult.model_validate(result.model_dump(mode="python"))


@pytest.mark.parametrize("window", [
    {"start": "2021-11-15", "end": "2021-11-16T00:00:00Z"},
    {"start": "2021-11-15T00:00:00", "end": "2021-11-16T00:00:00Z"},
    {"start": "2021-11-16T00:00:00Z", "end": "2021-11-16T00:00:00Z"},
    {"start": "2021-11-17T00:00:00Z", "end": "2021-11-16T00:00:00Z"},
])
def test_requested_window_must_be_aware_and_ordered(fusion_inputs, window):
    with pytest.raises(FusionValidationError):
        fuse_analysis(*fusion_inputs, requested_window=window)


def test_nonfinite_deep_evidence_is_rejected(fusion_inputs):
    fusion_inputs[2]["hydro"]["evidence"]["gpm"]["untrusted"] = {"value": float("nan")}
    with pytest.raises(FusionValidationError):
        fuse_analysis(*fusion_inputs)


def test_untyped_provenance_and_component_notes_fail_safely(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    combined["hydro"]["sources"][0]["resources_used"] = [{"not": "a resource name"}]
    with pytest.raises(FusionValidationError):
        fuse_analysis(hydro, flood, combined)
    combined["hydro"]["sources"][0]["resources_used"] = hydro["gpm_resources"]
    combined["flood"]["evidence"]["sentinel1"]["limitations"] = [{"not": "text"}]
    with pytest.raises(FusionValidationError, match="limitations"):
        fuse_analysis(hydro, flood, combined)


def test_dispatch_must_preserve_exact_source_results(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    combined.update(hydro=None, flood=None, errors=["Hydro unavailable.", "Flood unavailable."])
    instant = "2026-10-04T00:00:00Z"
    records = {}
    for role, task in (("hydro", hydro), ("flood", flood)):
        records[role] = {"task_id": task["task_id"], "worker_id": f"{role}-worker",
                         "analysis_type": task["analysis_type"], "outcome": "transport_error",
                         "control_started_at": instant, "control_completed_at": instant,
                         "error": {"code": "transport_error", "message": "Worker unavailable."}}
    dispatch = DispatchRun.model_validate({"task_id": hydro["task_id"], "execution_mode": "parallel",
                                          "control_started_at": instant, "control_completed_at": instant,
                                          **records, "combined": combined})
    result = fuse_analysis(hydro, flood, combined, dispatch=dispatch)
    assert result.dispatch == dispatch
    combined["errors"] = ["Changed collection."]
    with pytest.raises(FusionValidationError, match="Dispatch evidence"):
        fuse_analysis(hydro, flood, combined, dispatch=dispatch)
