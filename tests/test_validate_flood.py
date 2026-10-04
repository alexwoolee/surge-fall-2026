"""Exercise the terminal Phase 3C gate with actual small, local raster inputs."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import transform_bounds

from backend.workers.flood._raster import RasterTile
from backend.workers.flood.sentinel1 import Sentinel1Scene
from scripts.validate import validate_flood as validation


def _write_raster(path, values, transform, crs):
    values = np.asarray(values, dtype="float32")
    with rasterio.open(path, "w", driver="GTiff", height=values.shape[0],
                       width=values.shape[1], count=1, dtype="float32", crs=crs,
                       transform=transform, nodata=-32768) as dst:
        dst.write(values, 1)


@pytest.fixture
def local_case(tmp_path, monkeypatch):
    """Use production processors; replace only public resource discovery."""
    bbox = list(transform_bounds("EPSG:32610", "EPSG:4326",
                                 500000, 5499980, 500040, 5500000))
    rtc = tmp_path / "rtc.tif"
    _write_raster(rtc, [[0.001, 0.01, 0.1, 1], [0.004, 0.04, 0.01, 1]],
                  from_origin(500000, 5500000, 10, 10), "EPSG:32610")
    scene = Sentinel1Scene("fixture-rtc", str(rtc), "2021-11-15T12:00:00Z", tuple(bbox))
    grid = from_bounds(*bbox, width=4, height=2)
    tiles = {}
    for component, collection, values in [
        ("dem", "cop-dem-glo-30", [[-2, 1, 10, 20], [100, 200, 300, 400]]),
        ("hand", "glo-30-hand", [[0, 1, 2, 3], [4, 5, 6, 7]]),
    ]:
        tiles[component] = []
        for index in range(2):
            path = tmp_path / f"{component}-{index}.tif"
            _write_raster(path, np.asarray(values)[:, index * 2:(index + 1) * 2],
                          grid @ rasterio.Affine.translation(index * 2, 0), "EPSG:4326")
            tiles[component].append(RasterTile(f"{component}-{index}", str(path), collection))
    config = {
        "id": "local-flood-case", "bbox": bbox,
        "sentinel1_smoke_start": "2021-11-13T00:00:00Z",
        "sentinel1_smoke_end": "2021-11-18T23:59:59Z",
        "event_end": "2021-11-16T23:59:59Z",
    }
    config_path = tmp_path / "case.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(validation, "discover_sentinel1_scene", lambda *args, **kwargs: scene)
    monkeypatch.setattr(validation, "discover_dem_tiles", lambda *args, **kwargs: tiles["dem"])
    monkeypatch.setattr(validation, "discover_hand_tiles", lambda *args, **kwargs: tiles["hand"])
    return config_path, bbox, scene, tiles["dem"], tiles["hand"]


def _run(tmp_path, local_case, *extra):
    output = tmp_path / "checkpoint" / "result.json"
    status = validation.main(["--config", str(local_case[0]), "--output", str(output), *extra])
    return status, json.loads(output.read_text()), output


@pytest.fixture
def complete_result(local_case):
    _, bbox, scene, dem, hand = local_case
    return validation.run_flood_analysis(scene, dem, hand, bbox,
                                         task_id="phase3c-real-validation")


def test_local_processing_passes_terminal_gate_and_reversed_order_repeatability(
    tmp_path, local_case, monkeypatch, capsys,
):
    original = validation.run_flood_analysis
    calls = []

    def tracked_worker(scene, dem, hand, bbox, **kwargs):
        calls.append(([tile.tile_id for tile in dem], [tile.tile_id for tile in hand], kwargs))
        return original(scene, dem, hand, bbox, **kwargs)

    monkeypatch.setattr(validation, "run_flood_analysis", tracked_worker)
    status, report, output = _run(tmp_path, local_case, "--check-repeatability")
    assert status == 0
    assert report["real_data_check"] == "PASS"
    assert report["manual_review"] == "PENDING"
    assert report["repeatability_checked"] is True
    assert report["test_case"] == "local-flood-case"
    assert report["result"]["summary"]["surface_water"]["candidate_area_km2"] == pytest.approx(0.0004)
    assert report["result"]["summary"]["elevation"]["valid_pixels"] == 8
    assert calls[1][0] == list(reversed(calls[0][0]))
    assert calls[1][1] == list(reversed(calls[0][1]))
    assert calls[0][2] == calls[1][2]
    assert sorted(path.name for path in output.parent.iterdir()) == ["result.json"]
    assert not list(tmp_path.rglob("*.html"))
    terminal = capsys.readouterr().out
    assert "Phase 3C real-data check: PASS" in terminal
    assert "candidate water is not confirmed flooding" in terminal


def test_failed_discovery_invalidates_stale_pass_before_network_and_redacts_error(
    tmp_path, local_case, monkeypatch, capsys,
):
    output = tmp_path / "checkpoint" / "result.json"
    output.parent.mkdir()
    output.write_text(json.dumps({"real_data_check": "PASS", "result": "stale"}))

    def fail_discovery(*args, **kwargs):
        running = json.loads(output.read_text())
        assert running["real_data_check"] == "RUNNING"
        assert running["result"] is None
        raise RuntimeError("Cannot fetch https://provider.test/a.tif?sig=secret-token")

    monkeypatch.setattr(validation, "discover_sentinel1_scene", fail_discovery)
    status, report, _ = _run(tmp_path, local_case)
    assert status == 1
    assert report["real_data_check"] == "FAIL"
    assert report["manual_review"] == "NOT_READY"
    assert report["result"] is None
    assert "secret-token" not in json.dumps(report) + capsys.readouterr().out


def test_partial_worker_result_is_retained_in_failed_checkpoint(
    tmp_path, local_case, complete_result, monkeypatch,
):
    partial = deepcopy(complete_result)
    partial["status"] = "partial"
    partial["errors"] = [{"component": "hand", "message": "HAND could not be processed."}]
    partial["evidence"].pop("hand")
    partial["coverage"].pop("hand")
    partial["summary"].pop("hand")
    partial["sources"] = [source for source in partial["sources"] if source["component"] != "hand"]
    monkeypatch.setattr(validation, "run_flood_analysis", lambda *args, **kwargs: partial)
    status, report, _ = _run(tmp_path, local_case)
    assert status == 1
    assert report["real_data_check"] == "FAIL"
    assert report["result"] == partial
    assert report["result"]["evidence"]["dem"] == complete_result["evidence"]["dem"]
    assert "All three processors" in report["error"]


def test_repeatability_difference_fails_gate_and_retains_original_result(
    tmp_path, local_case, complete_result, monkeypatch, capsys,
):
    repeated = deepcopy(complete_result)
    repeated["limitations"].append("Unexpected repeat-only difference.")
    results = iter([complete_result, repeated])
    monkeypatch.setattr(validation, "run_flood_analysis", lambda *args, **kwargs: next(results))
    status, report, _ = _run(tmp_path, local_case, "--check-repeatability")
    assert status == 1
    assert report["real_data_check"] == "FAIL"
    assert report["result"] == complete_result
    assert "Repeated worker run changed" in report["error"]
    assert "check: PASS" not in capsys.readouterr().out


@pytest.mark.parametrize("mutation", [
    lambda result: result["summary"]["surface_water"].update(candidate_area_km2=999),
    lambda result: result["summary"]["elevation"].update(mean_m=999),
    lambda result: result["coverage"]["dem"].update(valid_pixels=999),
    lambda result: result["evidence"]["sentinel1"]["scene"].update(scene_id="wrong-scene"),
    lambda result: result["evidence"]["hand"]["source_tiles"][0].update(tile_id="wrong-tile"),
    lambda result: result["sources"].pop(),
    lambda result: result["sources"][0].update(resources_used=["wrong-resource"]),
    lambda result: result["sources"][0].update(acquired_at="2021-11-01T00:00:00Z"),
    lambda result: result["sources"][1].update(resources_used=["wrong-resource"]),
    lambda result: result["sources"][2].update(collection="wrong-collection"),
    lambda result: result["sources"].append(deepcopy(result["sources"][0])),
], ids=["water-summary", "terrain-summary", "coverage", "scene", "tile", "missing-source",
        "sar-resource", "sar-acquisition", "dem-resource", "hand-collection", "duplicate-source"])
def test_inconsistent_combined_results_fail_checkpoint(
    tmp_path, local_case, complete_result, monkeypatch, mutation,
):
    mutation(complete_result)
    monkeypatch.setattr(validation, "run_flood_analysis", lambda *args, **kwargs: complete_result)
    status, report, _ = _run(tmp_path, local_case)
    assert status == 1
    assert report["real_data_check"] == "FAIL"
    assert report["manual_review"] == "NOT_READY"


def test_invalid_config_fails_without_resource_access(tmp_path, local_case, monkeypatch):
    local_case[0].write_text("not JSON", encoding="utf-8")

    def unexpected_discovery(*args, **kwargs):
        pytest.fail("Invalid configuration must fail before external resource access.")

    monkeypatch.setattr(validation, "discover_sentinel1_scene", unexpected_discovery)
    status, report, _ = _run(tmp_path, local_case)
    assert status == 1
    assert report["real_data_check"] == "FAIL"
    assert report["result"] is None


def test_report_save_failure_never_announces_pass(tmp_path, local_case, monkeypatch, capsys):
    original = Path.write_text

    def fail_completed_report(path, text, *args, **kwargs):
        if path.name == "result.json" and json.loads(text)["real_data_check"] == "PASS":
            raise OSError("Disk unavailable.")
        return original(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_completed_report)
    status, report, _ = _run(tmp_path, local_case)
    assert status == 1
    assert report["real_data_check"] == "RUNNING"
    terminal = capsys.readouterr().out
    assert "check: PASS" not in terminal
    assert "could not save a valid result report" in terminal
