"""Flood worker integration: preserve independent evidence and explicit failures.

The local fixtures use different native SAR/DEM/HAND grids so a successful
worker cannot accidentally depend on pixelwise alignment or infer water depth.
No catalogs, network requests, or generated review pages are needed.
"""

from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import transform_bounds

from backend.workers.flood import service
from backend.workers.flood._raster import RasterTile, TerrainProcessingError
from backend.workers.flood.hand import HAND_COLLECTION, analyze_hand_tiles
from backend.workers.flood.sentinel1 import (
    Sentinel1ProcessingError,
    Sentinel1Scene,
    analyze_sentinel1_scene,
)
from backend.workers.flood.terrain import DEM_COLLECTION, analyze_dem_tiles


COMPONENTS = ("sentinel1", "dem", "hand")
SUMMARY_KEYS = {"sentinel1": "surface_water", "dem": "elevation", "hand": "hand"}
PROCESSORS = {
    "sentinel1": "analyze_sentinel1_scene",
    "dem": "analyze_dem_tiles",
    "hand": "analyze_hand_tiles",
}


def write_raster(path, values, grid, crs):
    values = np.asarray(values, dtype="float32")
    with rasterio.open(
        path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
        count=1, dtype="float32", crs=crs, transform=grid,
    ) as target:
        target.write(values, 1)


@pytest.fixture
def resources(tmp_path):
    sar_grid = from_origin(500_000, 40, 10, 10)
    bbox = transform_bounds("EPSG:32631", "EPSG:4326", 500_000, 20, 500_020, 40)
    sar_path = tmp_path / "sar.tif"
    write_raster(sar_path, [[0.01, 0.1], [1, 0.001]], sar_grid, "EPSG:32631")
    scene = Sentinel1Scene(
        scene_id="approved-rtc-scene", href=str(sar_path), bbox=bbox,
        acquired_at="2021-11-15T14:00:00Z", orbit_state="descending", relative_orbit=42,
    )
    dem_path = tmp_path / "dem.tif"
    write_raster(
        dem_path, [[-2, 0, 10, 20], [30, 40, 50, 60]],
        from_bounds(*bbox, 4, 2), "EPSG:4326",
    )
    hand_path = tmp_path / "hand.tif"
    write_raster(
        hand_path, [[0, 1, 2], [3, 4, 8]],
        from_bounds(*bbox, 3, 2), "EPSG:4326",
    )
    return {
        "scene": scene, "bbox": bbox,
        "dem_tiles": [RasterTile("dem-local", str(dem_path), DEM_COLLECTION)],
        "hand_tiles": [RasterTile("hand-local", str(hand_path), HAND_COLLECTION)],
    }


@pytest.fixture
def evidence(resources):
    return {
        "sentinel1": analyze_sentinel1_scene(resources["scene"], resources["bbox"]),
        "dem": analyze_dem_tiles(resources["dem_tiles"], resources["bbox"]),
        "hand": analyze_hand_tiles(resources["hand_tiles"], resources["bbox"]),
    }


def mock_processors(monkeypatch, evidence):
    mocks = {}
    for component, function_name in PROCESSORS.items():
        mocks[component] = Mock(return_value=deepcopy(evidence[component]))
        monkeypatch.setattr(service, function_name, mocks[component])
    return mocks


def assert_summary_matches_evidence(result):
    for component, data in result["evidence"].items():
        summary = result["summary"][SUMMARY_KEYS[component]]
        assert result["coverage"][component] == data["coverage"]
        assert summary["valid_fraction"] == data["coverage"]["valid_fraction"]
        if component == "sentinel1":
            assert summary["candidate_area_km2"] == data["candidate_water"]["area_km2"]
            assert summary["candidate_fraction_valid"] == data["candidate_water"]["fraction_valid"]
            assert summary["scene_id"] == data["scene"]["scene_id"]
            assert summary["acquired_at"] == data["scene"]["acquired_at"]
            assert summary["threshold_db"] == data["method"]["threshold_db"]
        else:
            for name in ("mean", "min", "max", "median"):
                assert summary[f"{name}_m"] == data["statistics"][name]
            assert summary["valid_pixels"] == data["statistics"]["count"]
            assert summary["tile_count"] == len(data["source_tiles"])


def test_actual_local_worker_combines_different_grids_without_derived_flood_claims(resources, tmp_path):
    before = set(tmp_path.rglob("*"))
    result = service.run_flood_analysis(**resources, task_id="local-integration")
    assert result["status"] == "complete"
    assert result["task_id"] == "local-integration"
    assert result["worker_id"] == "flood-worker"
    assert result["analysis_type"] == "surface_water_and_terrain"
    assert result["errors"] == []
    assert result["bbox"] == dict(zip(("west", "south", "east", "north"), resources["bbox"]))
    assert set(result["evidence"]) == set(COMPONENTS)
    assert result["summary"]["surface_water"]["candidate_area_km2"] == 0.0002
    assert result["summary"]["surface_water"]["candidate_fraction_valid"] == 0.5
    assert result["summary"]["elevation"]["mean_m"] == 26
    assert result["summary"]["elevation"]["min_m"] == -2
    assert result["summary"]["hand"]["mean_m"] == 3
    assert result["summary"]["hand"]["min_m"] == 0
    assert [result["evidence"][key]["coverage"]["valid_pixels"] for key in COMPONENTS] == [4, 8, 6]
    assert result["evidence"]["sentinel1"]["raster"]["crs"] == "EPSG:32631"
    assert result["evidence"]["dem"]["raster"]["crs"] == "EPSG:4326"
    assert_summary_matches_evidence(result)
    assert [entry["component"] for entry in result["sources"]] == list(COMPONENTS)
    assert all(entry["resources_used"] for entry in result["sources"])
    assert all(result["evidence"][key]["limitations"] for key in COMPONENTS)
    limits = " ".join(result["limitations"]).lower()
    assert "not" in limits and "flood" in limits
    assert not {"severity", "flood_depth", "confirmed_flood", "probability"}.intersection(result["summary"])
    assert set(tmp_path.rglob("*")) == before
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_explicit_task_results_repeat_and_generated_ids_are_distinct(resources):
    assert service.run_flood_analysis(**resources, task_id="same") == service.run_flood_analysis(**resources, task_id="same")
    first = service.run_flood_analysis(**resources)
    second = service.run_flood_analysis(**resources)
    assert isinstance(first["task_id"], str) and first["task_id"].strip()
    assert first["task_id"] != second["task_id"]
    first.pop("task_id")
    second.pop("task_id")
    assert first == second


@pytest.mark.parametrize("failed", [
    {"sentinel1"}, {"dem"}, {"hand"}, {"sentinel1", "dem"}, set(COMPONENTS),
])
def test_component_failure_preserves_other_evidence_and_always_attempts_all(resources, evidence, monkeypatch, failed):
    mocks = mock_processors(monkeypatch, evidence)
    for component in failed:
        error = Sentinel1ProcessingError if component == "sentinel1" else TerrainProcessingError
        mocks[component].side_effect = error("Access failed https://user:password@example.test/data?sig=secret#private")
    result = service.run_flood_analysis(**resources, task_id="failure-test")
    successful = set(COMPONENTS) - failed
    assert result["status"] == ("failed" if not successful else "partial")
    assert set(result["evidence"]) == successful
    assert set(result["coverage"]) == successful
    assert set(result["summary"]) == {SUMMARY_KEYS[key] for key in successful}
    assert {entry["component"] for entry in result["errors"]} == failed
    assert {entry["component"] for entry in result["sources"]} == successful
    assert all(error["code"] == "processing_failed" and error["message"] for error in result["errors"])
    for component, mock in mocks.items():
        mock.assert_called_once()
        if component in successful:
            assert result["evidence"][component] == evidence[component]
    assert_summary_matches_evidence(result)
    serialized = json.dumps(result, allow_nan=False)
    assert all(secret not in serialized for secret in ("password", "sig=secret", "#private"))


def test_unexpected_component_exception_is_sanitized_and_does_not_hide_other_results(resources, evidence, monkeypatch):
    mocks = mock_processors(monkeypatch, evidence)
    mocks["dem"].side_effect = RuntimeError("Private token = do-not-echo")
    result = service.run_flood_analysis(**resources)
    assert result["status"] == "partial"
    assert set(result["evidence"]) == {"sentinel1", "hand"}
    assert "do-not-echo" not in json.dumps(result, allow_nan=False)
    assert result["errors"][0]["component"] == "dem"


def test_actual_unavailable_raster_preserves_working_components(resources, tmp_path):
    unavailable = replace(resources["dem_tiles"][0], href=str(tmp_path / "missing.tif"))
    result = service.run_flood_analysis(**{**resources, "dem_tiles": [unavailable]})
    assert result["status"] == "partial"
    assert set(result["evidence"]) == {"sentinel1", "hand"}
    assert result["errors"][0]["component"] == "dem"
    assert result["errors"][0]["code"] == "processing_failed"
    assert_summary_matches_evidence(result)


def test_partial_valid_coverage_is_measured_evidence_not_worker_failure(resources):
    with rasterio.open(resources["scene"].href, "r+") as target:
        target.write(np.array([[0.01, 0], [1, 0.001]], dtype="float32"), 1)
    result = service.run_flood_analysis(**resources)
    assert result["status"] == "complete"
    assert result["errors"] == []
    assert result["coverage"]["sentinel1"]["status"] == "partial"
    assert result["coverage"]["sentinel1"]["valid_fraction"] == 0.75
    assert result["summary"]["surface_water"]["candidate_fraction_valid"] == pytest.approx(2 / 3)
    assert result["summary"]["surface_water"]["candidate_area_km2"] == 0.0002
    assert_summary_matches_evidence(result)


def test_worker_passes_bounded_options_to_processors(resources, evidence, monkeypatch):
    mocks = mock_processors(monkeypatch, evidence)
    # Supply matching real evidence for the nondefault threshold.
    mocks["sentinel1"].return_value = analyze_sentinel1_scene(resources["scene"], resources["bbox"], threshold_db=-20)
    result = service.run_flood_analysis(
        **resources, threshold_db=-20, terrain_max_pixels=40, sentinel_max_pixels=50,
    )
    assert result["status"] == "complete"
    for component in COMPONENTS:
        args, kwargs = mocks[component].call_args
        assert tuple(args[1]) == resources["bbox"]
        assert kwargs["max_pixels"] == (50 if component == "sentinel1" else 40)
        assert kwargs.get("output_dir") is None
        assert kwargs.get("output_path") is None
    assert mocks["sentinel1"].call_args.kwargs["threshold_db"] == -20


@pytest.mark.parametrize("change", [
    {"bbox": (3, 0, 3, 1)}, {"bbox": (3, 0, float("nan"), 1)},
    {"task_id": ""}, {"task_id": "  "}, {"task_id": 10},
    {"threshold_db": float("nan")}, {"threshold_db": -41}, {"threshold_db": True},
    {"terrain_max_pixels": 0}, {"terrain_max_pixels": True},
    {"sentinel_max_pixels": 1.5}, {"sentinel_max_pixels": -1},
    {"dem_tiles": []}, {"hand_tiles": []}, {"dem_tiles": "not-tiles"},
    {"scene": None},
])
def test_invalid_request_is_rejected_before_any_processor_io(resources, evidence, monkeypatch, change):
    mocks = mock_processors(monkeypatch, evidence)
    with pytest.raises(service.FloodWorkerError):
        service.run_flood_analysis(**{**resources, **change})
    assert all(mock.call_count == 0 for mock in mocks.values())


@pytest.mark.parametrize("change", [
    {"collection": "sentinel-1-grd"}, {"polarization": "VH"},
    {"acquired_at": "not-a-date"}, {"scene_id": ""},
])
def test_unsupported_scene_metadata_is_rejected_before_any_io(resources, evidence, monkeypatch, change):
    mocks = mock_processors(monkeypatch, evidence)
    with pytest.raises(service.FloodWorkerError):
        service.run_flood_analysis(**{**resources, "scene": replace(resources["scene"], **change)})
    assert all(mock.call_count == 0 for mock in mocks.values())


@pytest.mark.parametrize("component, changes", [
    ("dem", {"collection": HAND_COLLECTION}),
    ("hand", {"collection": DEM_COLLECTION}),
    ("dem", {"tile_id": ""}),
    ("hand", {"href": ""}),
])
def test_invalid_terrain_metadata_is_rejected_before_any_io(resources, evidence, monkeypatch, component, changes):
    mocks = mock_processors(monkeypatch, evidence)
    field = f"{component}_tiles"
    invalid = [replace(resources[field][0], **changes)]
    with pytest.raises(service.FloodWorkerError):
        service.run_flood_analysis(**{**resources, field: invalid})
    assert all(mock.call_count == 0 for mock in mocks.values())


@pytest.mark.parametrize("component, limit", [("dem", 128), ("hand", 256)])
def test_resource_generators_are_bounded_before_processing(resources, evidence, monkeypatch, component, limit):
    mocks = mock_processors(monkeypatch, evidence)
    consumed = []
    prototype = resources[f"{component}_tiles"][0]

    def too_many():
        for index in range(limit + 2):
            consumed.append(index)
            yield replace(prototype, tile_id=f"tile-{index}")
        pytest.fail("Unbounded resource generator was consumed.")

    with pytest.raises(service.FloodWorkerError):
        service.run_flood_analysis(**{**resources, f"{component}_tiles": too_many()})
    assert len(consumed) <= limit + 1
    assert all(mock.call_count == 0 for mock in mocks.values())


def test_valid_resource_generators_match_lists(resources):
    expected = service.run_flood_analysis(**resources, task_id="iterable")
    result = service.run_flood_analysis(
        **{**resources, "dem_tiles": iter(resources["dem_tiles"]), "hand_tiles": iter(resources["hand_tiles"])},
        task_id="iterable",
    )
    assert result == expected


@pytest.mark.parametrize("component, corrupt", [
    ("sentinel1", None), ("dem", {}), ("hand", {"statistics": {"mean": float("nan")}}),
])
def test_malformed_processor_result_is_component_failure_not_fabricated_summary(resources, evidence, monkeypatch, component, corrupt):
    mocks = mock_processors(monkeypatch, evidence)
    mocks[component].return_value = corrupt
    result = service.run_flood_analysis(**resources)
    assert result["status"] == "partial"
    assert component not in result["evidence"]
    assert SUMMARY_KEYS[component] not in result["summary"]
    assert result["errors"][0]["component"] == component
    assert result["errors"][0]["code"] == "invalid_result"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("component, corrupt", [
    ("dem", lambda data: data["statistics"].update(mean=float("nan"))),
    ("sentinel1", lambda data: data["candidate_water"].update(area_km2=999)),
    ("hand", lambda data: data["coverage"].update(valid_fraction=0.1)),
    ("sentinel1", lambda data: data["scene"].update(scene_id="wrong-scene")),
    ("dem", lambda data: data["source_tiles"][0].update(href="https://different.test/unrequested.tif")),
    ("hand", lambda data: data.update(bbox=[4, 0, 5, 1])),
])
def test_inconsistent_evidence_is_rejected_before_becoming_authoritative_summary(resources, evidence, monkeypatch, component, corrupt):
    mocks = mock_processors(monkeypatch, evidence)
    corrupt(mocks[component].return_value)
    result = service.run_flood_analysis(**resources)
    assert result["status"] == "partial"
    assert component not in result["evidence"]
    assert result["errors"][0]["component"] == component
    assert result["errors"][0]["code"] == "invalid_result"
    assert_summary_matches_evidence(result)
    json.dumps(result, allow_nan=False)


def test_signed_asset_access_is_preserved_but_all_published_source_hrefs_are_sanitized(resources, evidence, monkeypatch):
    signed = {
        key: f"https://operator:password@example.test/{key}.tif?sig=secret#private"
        for key in COMPONENTS
    }
    request = {
        **resources,
        "scene": replace(resources["scene"], href=signed["sentinel1"]),
        "dem_tiles": [replace(resources["dem_tiles"][0], href=signed["dem"])],
        "hand_tiles": [replace(resources["hand_tiles"][0], href=signed["hand"])],
    }
    mocks = mock_processors(monkeypatch, evidence)
    mocks["sentinel1"].return_value["scene"]["href"] = signed["sentinel1"]
    for component in ("dem", "hand"):
        mocks[component].return_value["source_tiles"][0]["href"] = signed[component]
    result = service.run_flood_analysis(**request)
    assert result["status"] == "complete"
    assert mocks["sentinel1"].call_args.args[0].href == signed["sentinel1"]
    for component in ("dem", "hand"):
        assert mocks[component].call_args.args[0][0].href == signed[component]
    for source in result["sources"]:
        assert source["resources_used"] == [f"https://example.test/{source['component']}.tif"]
    assert result["evidence"]["sentinel1"]["scene"]["href"] == "https://example.test/sentinel1.tif"
    for component in ("dem", "hand"):
        assert result["evidence"][component]["source_tiles"][0]["href"] == f"https://example.test/{component}.tif"
    serialized = json.dumps(result, allow_nan=False)
    assert all(secret not in serialized for secret in ("operator", "password", "sig=secret", "#private"))
    # Sanitizing the public payload must not mutate processor-owned evidence.
    assert mocks["sentinel1"].return_value["scene"]["href"] == signed["sentinel1"]
