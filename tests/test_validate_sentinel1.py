"""Protect the Phase 3B real-data gate against stale or inconsistent evidence."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin, Affine
from rasterio.warp import transform_bounds

from backend.workers.flood.sentinel1 import (
    Sentinel1ProcessingError, Sentinel1Scene, analyze_sentinel1_scene,
)
from scripts.validate import validate_sentinel1 as validation


@pytest.fixture
def evidence(tmp_path):
    source = tmp_path / "rtc.tif"
    grid = from_origin(500000, 5500000, 10, 10)
    power = np.array([[0.001, 0.01, 0.1], [0.004, 0.04, 1]], dtype="float32")
    with rasterio.open(source, "w", driver="GTiff", height=2, width=3,
                       count=1, dtype="float32", crs="EPSG:32610",
                       transform=grid, nodata=-32768) as dst:
        dst.write(power, 1)
    bbox = transform_bounds("EPSG:32610", "EPSG:4326", 500000, 5499980, 500030, 5500000)
    scene = Sentinel1Scene("fixture-rtc", str(source), "2021-11-15T12:00:00Z", bbox)
    return analyze_sentinel1_scene(scene, bbox, output_dir=tmp_path / "rasters")


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "case.json"
    path.write_text(json.dumps({
        "id": "test-case", "bbox": [-123.1, 49.0, -122.9, 49.2],
        "sentinel1_smoke_start": "2021-11-13T00:00:00Z",
        "sentinel1_smoke_end": "2021-11-18T23:59:59Z",
        "event_end": "2021-11-16T23:59:59Z",
    }))
    return path


def test_delivered_artifacts_reconcile_with_numerical_report(evidence):
    histogram = validation._check_rasters(evidence)
    assert sum(histogram["counts"]) + histogram["outside_histogram_range"] == 6
    assert evidence["candidate_water"]["count"] == 3
    assert evidence["candidate_water"]["area_km2"] == pytest.approx(0.0003)


def test_candidate_threshold_tampering_fails_gate(evidence):
    with rasterio.open(evidence["artifacts"]["candidate_water"], "r+") as dst:
        mask = dst.read(1)
        row, col = np.argwhere(mask == 0)[0]
        mask[row, col] = 1
        dst.write(mask, 1)
    with pytest.raises(Sentinel1ProcessingError, match="documented threshold"):
        validation._check_rasters(evidence)


def test_candidate_grid_tampering_fails_gate(evidence):
    with rasterio.open(evidence["artifacts"]["candidate_water"], "r+") as dst:
        dst.transform = dst.transform @ Affine.translation(1, 0)
    with pytest.raises(Sentinel1ProcessingError, match="grids differ"):
        validation._check_rasters(evidence)


def test_candidate_nodata_tampering_fails_gate(evidence):
    with rasterio.open(evidence["artifacts"]["candidate_water"], "r+") as dst:
        dst.nodata = 254
    with pytest.raises(Sentinel1ProcessingError, match="255 as nodata"):
        validation._check_rasters(evidence)


def test_backscatter_nodata_tampering_fails_gate(evidence):
    with rasterio.open(evidence["artifacts"]["backscatter_db"], "r+") as dst:
        dst.nodata = -9999
    with pytest.raises(Sentinel1ProcessingError, match="NaN nodata"):
        validation._check_rasters(evidence)


@pytest.mark.parametrize("field,value", [
    ("crs", "EPSG:32611"), ("width", 999), ("height", 999),
    ("transform", [10, 0, 0, 0, -10, 0]), ("resolution", [20, 20]),
    ("pixel_area_m2", 400),
])
def test_reported_grid_metadata_tampering_fails_gate(evidence, field, value):
    evidence["raster"][field] = value
    with pytest.raises(Sentinel1ProcessingError, match="grid metadata differs"):
        validation._check_rasters(evidence)


def test_candidate_invalid_class_fails_gate(evidence):
    with rasterio.open(evidence["artifacts"]["candidate_water"], "r+") as dst:
        mask = dst.read(1)
        row, col = np.argwhere(mask == 0)[0]
        mask[row, col] = 2
        dst.write(mask, 1)
    with pytest.raises(Sentinel1ProcessingError, match="valid-data masks differ"):
        validation._check_rasters(evidence)


@pytest.mark.parametrize("field", ["min", "max", "mean", "median"])
def test_backscatter_statistic_tampering_fails_gate(evidence, field):
    evidence["backscatter_db"][field] += 1
    with pytest.raises(Sentinel1ProcessingError, match=f"Artifact {field}"):
        validation._check_rasters(evidence)


def test_candidate_area_tampering_fails_gate(evidence):
    evidence["candidate_water"]["area_km2"] += 1
    with pytest.raises(Sentinel1ProcessingError, match="count or area"):
        validation._check_rasters(evidence)


@pytest.mark.parametrize("field,value,message", [
    ("coverage_fraction", 0.99, "full AOI raster coverage"),
    ("valid_fraction", 0.949, "AOI coverage differs"),
])
def test_inadequate_coverage_fails_real_data_gate(evidence, field, value, message):
    evidence["coverage"][field] = value
    with pytest.raises(Sentinel1ProcessingError, match=message):
        validation._check_rasters(evidence)


def test_correctly_reported_valid_coverage_below_95_percent_fails_gate(evidence):
    scene_data = evidence["scene"]
    with rasterio.open(scene_data["href"], "r+") as dst:
        power = dst.read(1)
        power[1, 2] = -32768
        dst.write(power, 1)
    scene = Sentinel1Scene(scene_data["scene_id"], scene_data["href"],
                           scene_data["acquired_at"], tuple(scene_data["bbox"]))
    incomplete = analyze_sentinel1_scene(
        scene, evidence["bbox"], output_dir=Path(evidence["artifacts"]["backscatter_db"]).parent,
    )
    assert incomplete["coverage"]["valid_fraction"] == pytest.approx(5 / 6)
    with pytest.raises(Sentinel1ProcessingError, match="at least 95%"):
        validation._check_rasters(incomplete)


def test_discovery_failure_invalidates_previous_pass_before_network_call(
    tmp_path, config_path, monkeypatch,
):
    output = tmp_path / "review"
    output.mkdir()
    (output / "result.json").write_text(json.dumps({"real_data_check": "PASS"}))
    (output / "review.html").write_text("Earlier validation PASS")

    def failed_discovery(*args, **kwargs):
        current = json.loads((output / "result.json").read_text())
        assert current["real_data_check"] == "RUNNING"
        assert "Earlier validation PASS" not in (output / "review.html").read_text()
        raise Sentinel1ProcessingError("Provider unavailable.")

    monkeypatch.setattr(validation, "discover_sentinel1_scene", failed_discovery)
    assert validation.main(["--config", str(config_path), "--output-dir", str(output)]) == 1
    report = json.loads((output / "result.json").read_text())
    assert report["real_data_check"] == "FAIL"
    assert report["manual_review"] == "NOT_READY"
    assert "failed" in (output / "review.html").read_text()
    assert "PASS" not in (output / "review.html").read_text()


def test_repeatability_failure_prevents_pass_report(
    tmp_path, config_path, evidence, monkeypatch,
):
    output = tmp_path / "review"
    changed = deepcopy(evidence)
    changed["candidate_water"]["count"] += 1
    results = iter([evidence, changed])
    monkeypatch.setattr(validation, "discover_sentinel1_scene",
                        lambda *args, **kwargs: SimpleNamespace(scene_id="fixture"))
    monkeypatch.setattr(validation, "analyze_sentinel1_scene", lambda *args, **kwargs: next(results))

    def unexpected_review(*args, **kwargs):
        pytest.fail("A failed repeatability check must not publish a passing review.")

    monkeypatch.setattr(validation, "_write_review", unexpected_review)
    assert validation.main(["--config", str(config_path), "--output-dir", str(output),
                            "--check-repeatability"]) == 1
    report = json.loads((output / "result.json").read_text())
    assert report["real_data_check"] == "FAIL"
    assert "Repeated processing changed" in report["error"]


def test_passing_gate_keeps_user_manual_review_pending(
    tmp_path, config_path, evidence, monkeypatch,
):
    output = tmp_path / "review"
    repeated = deepcopy(evidence)
    repeated["artifacts"] = None
    results = iter([evidence, repeated])
    monkeypatch.setattr(validation, "discover_sentinel1_scene",
                        lambda *args, **kwargs: SimpleNamespace(scene_id="fixture"))
    monkeypatch.setattr(validation, "analyze_sentinel1_scene", lambda *args, **kwargs: next(results))
    assert validation.main(["--config", str(config_path), "--output-dir", str(output),
                            "--check-repeatability"]) == 0
    report = json.loads((output / "result.json").read_text())
    assert report["real_data_check"] == "PASS"
    assert report["manual_review"] == "PENDING"
    assert report["repeatability_checked"] is True
    assert (output / "backscatter.png").is_file()
    assert (output / "overlay.png").is_file()
    assert "Manual review: PENDING" in (output / "review.html").read_text()
