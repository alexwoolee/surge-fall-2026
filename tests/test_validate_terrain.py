"""Exercise the terrain review command with actual small raster fixtures."""

import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from backend.workers.flood._raster import RasterTile
from scripts.validate import validate_terrain


def inputs(tmp_path, monkeypatch, *, incomplete=False):
    config = tmp_path / "case.json"
    config.write_text(json.dumps({"id": "synthetic-test", "bbox": [0, 0, 2, 1]}))
    groups = {}
    for kind in ("dem", "hand"):
        tiles = []
        for column in range(1 if incomplete and kind == "hand" else 2):
            path = tmp_path / f"{kind}-{column}.tif"
            with rasterio.open(path, "w", driver="GTiff", count=1, width=2, height=2,
                               dtype="float32", crs="EPSG:4326",
                               transform=from_origin(column, 1, .5, .5)) as dst:
                dst.write(np.full((2, 2), column * 10, dtype="float32"), 1)
            tiles.append(RasterTile(f"{kind}-{column}", str(path)))
        groups[kind] = tiles
    monkeypatch.setattr(validate_terrain, "discover_dem_tiles", lambda bbox: groups["dem"])
    monkeypatch.setattr(validate_terrain, "discover_hand_tiles", lambda bbox: groups["hand"])
    output = tmp_path / "review"
    return ["--config", str(config), "--output-dir", str(output)], output


def test_command_writes_consistent_rasters_previews_and_manual_gate(tmp_path, monkeypatch):
    args, output = inputs(tmp_path, monkeypatch)
    assert validate_terrain.main([*args, "--check-repeatability"]) == 0
    report = json.loads((output / "result.json").read_text())
    assert report["real_data_check"] == "PASS"
    assert report["manual_review"] == "PENDING"
    assert report["repeatability_checked"] is True
    for kind in ("dem", "hand"):
        assert report["results"][kind]["statistics"]["count"] == 8
        assert report["results"][kind]["statistics"]["mean"] == 5
        assert (output / f"{kind}.tif").is_file()
        assert (output / f"{kind}.png").read_bytes().startswith(b"\x89PNG")
    assert "Manual approval remains pending" in (output / "review.html").read_text()


def test_missing_tiles_fail_gate_and_invalidate_old_review(tmp_path, monkeypatch):
    args, output = inputs(tmp_path, monkeypatch, incomplete=True)
    output.mkdir()
    (output / "review.html").write_text("stale success")
    assert validate_terrain.main(args) == 1
    report = json.loads((output / "result.json").read_text())
    assert report["real_data_check"] == "FAIL"
    assert report["manual_review"] == "NOT_READY"
    assert "validation failed" in (output / "review.html").read_text()


def test_missing_config_writes_failure_result(tmp_path):
    output = tmp_path / "result"
    assert validate_terrain.main([
        "--config", str(tmp_path / "absent.json"), "--output-dir", str(output),
    ]) == 1
    assert json.loads((output / "result.json").read_text())["real_data_check"] == "FAIL"
