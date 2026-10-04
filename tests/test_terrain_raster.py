"""Offline regression tests for bounded, multi-tile terrain processing."""

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin

from backend.workers.flood import _raster
from backend.workers.flood._raster import (
    RasterTile, TerrainProcessingError, analyze_raster_tiles, validate_bbox,
)


def write_tile(tmp_path, tile_id, data, *, west=0, north=2, crs="EPSG:4326",
               transform=None, nodata=None, mask=None, unit=None, scale=1, offset=0):
    path = tmp_path / f"{tile_id}.tif"
    values = np.asarray(data, dtype=np.float32)
    with rasterio.open(
        path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
        count=1, dtype="float32", crs=crs,
        transform=transform if transform is not None else from_origin(west, north, 1, 1),
        nodata=nodata,
    ) as destination:
        destination.write(values, 1)
        destination.scales = (scale,)
        destination.offsets = (offset,)
        if mask is not None:
            destination.write_mask(np.asarray(mask, dtype=np.uint8) * 255)
        if unit:
            destination.set_band_unit(1, unit)
    return RasterTile(tile_id, str(path), "synthetic-terrain")


def test_combines_all_adjacent_tiles_with_stable_provenance(tmp_path):
    left = write_tile(tmp_path, "left", [[1, 2], [3, 4]])
    right = write_tile(tmp_path, "right", [[5, 6], [7, 8]], west=2)
    result = analyze_raster_tiles([right, left], (0, 0, 4, 2))
    assert result["statistics"] == {
        "units": "m", "min": 1, "max": 8, "mean": 4.5, "median": 4.5, "count": 8,
    }
    assert result["coverage"] == {
        "aoi_pixels": 8, "covered_pixels": 8, "valid_pixels": 8,
        "coverage_fraction": 1, "valid_fraction": 1, "status": "complete",
    }
    assert [tile["tile_id"] for tile in result["source_tiles"]] == ["left", "right"]
    assert all(tile["contributed_pixels"] == 4 for tile in result["source_tiles"])
    assert result == analyze_raster_tiles([left, right], (0, 0, 4, 2))
    json.dumps(result, allow_nan=False)


def test_clipping_uses_centers_and_saved_geotiff_masks_outside_aoi(tmp_path):
    tile = write_tile(tmp_path, "large", np.arange(16).reshape(4, 4), north=4)
    output = tmp_path / "artifact" / "clipped.tif"
    result = analyze_raster_tiles([tile], (0.6, 0.6, 3.4, 3.4), output_path=output)
    assert result["statistics"]["count"] == 4
    assert result["statistics"]["mean"] == 7.5
    assert result["bbox"] == [0.6, 0.6, 3.4, 3.4]
    assert result["artifact_path"] == str(output.resolve())
    with rasterio.open(output) as artifact:
        values = artifact.read(1, masked=True)
        np.testing.assert_array_equal(values.compressed(), [5, 6, 9, 10])
        assert artifact.crs.to_epsg() == 4326
        assert artifact.units == ("m",)
        assert artifact.transform == from_origin(0, 4, 1, 1)


@pytest.mark.parametrize("bbox,count,mean", [
    ((0.05, 0.05, 0.15, 0.15), 4, 85.5),
    ((0.05, 0.05, 0.95, 0.95), 100, 49.5),
])
def test_inclusive_pixel_center_edges_tolerate_floating_roundoff(tmp_path, bbox, count, mean):
    tile = write_tile(
        tmp_path, "decimal-grid", np.arange(100).reshape(10, 10),
        transform=from_origin(0, 1, 0.1, 0.1),
    )
    result = analyze_raster_tiles([tile], bbox)
    assert result["statistics"]["count"] == count
    assert result["statistics"]["mean"] == mean
    assert result["coverage"]["aoi_pixels"] == count
    assert result["coverage"]["status"] == "complete"


@pytest.mark.parametrize("bbox,expected", [
    ((0.05 + 1e-10, 0.05 + 1e-10, 0.15, 0.15), 81),
    ((0.05, 0.05, 0.15 - 1e-10, 0.15 - 1e-10), 90),
])
def test_boundary_tolerance_does_not_admit_meaningfully_outside_centers(tmp_path, bbox, expected):
    tile = write_tile(
        tmp_path, "decimal-grid", np.arange(100).reshape(10, 10),
        transform=from_origin(0, 1, 0.1, 0.1),
    )
    result = analyze_raster_tiles([tile], bbox)
    assert result["statistics"]["count"] == 1
    assert result["statistics"]["mean"] == expected


def test_overlap_first_valid_sorted_tile_wins_and_later_tile_fills_nodata(tmp_path):
    first = write_tile(tmp_path, "a", [[1, -9999], [np.nan, 0]], nodata=-9999)
    second = write_tile(tmp_path, "b", [[9, 2], [3, 4]])
    result = analyze_raster_tiles([second, first], (0, 0, 2, 2))
    assert result["statistics"] == {
        "units": "m", "min": 0, "max": 3, "mean": 1.5, "median": 1.5, "count": 4,
    }
    assert [tile["contributed_pixels"] for tile in result["source_tiles"]] == [2, 2]
    assert [tile["valid_pixels"] for tile in result["source_tiles"]] == [2, 4]
    assert result["coverage"]["covered_pixels"] == 4


def test_hand_zero_valid_negative_and_nonfinite_invalid_without_nodata(tmp_path):
    tile = write_tile(tmp_path, "hand", [[0, -2], [5, np.inf]])
    result = analyze_raster_tiles([tile], (0, 0, 2, 2), kind="hand")
    assert result["statistics"] == {
        "units": "m", "min": 0, "max": 5, "mean": 2.5, "median": 2.5, "count": 2,
    }
    assert result["coverage"]["coverage_fraction"] == 1
    assert result["coverage"]["valid_fraction"] == 0.5
    assert result["coverage"]["status"] == "partial"
    assert any("Undeclared positive sentinel" in text for text in result["limitations"])
    assert any("not a flood detector" in text for text in result["limitations"])


def test_dem_below_sea_level_remains_valid(tmp_path):
    tile = write_tile(tmp_path, "dem", [[-3, 0], [1, 2]])
    result = analyze_raster_tiles([tile], (0, 0, 2, 2))
    assert result["statistics"]["min"] == -3
    assert result["statistics"]["mean"] == 0
    assert result["statistics"]["count"] == 4


def test_missing_tile_gap_is_explicit_in_coverage_and_artifact(tmp_path):
    left = write_tile(tmp_path, "left", np.ones((2, 2)))
    right = write_tile(tmp_path, "right", np.ones((2, 2)) * 3, west=4)
    output = tmp_path / "gap.tif"
    result = analyze_raster_tiles([left, right], (0, 0, 6, 2), output_path=output)
    assert result["statistics"]["count"] == 8
    assert result["statistics"]["mean"] == 2
    assert result["coverage"] == {
        "aoi_pixels": 12, "covered_pixels": 8, "valid_pixels": 8,
        "coverage_fraction": 8 / 12, "valid_fraction": 8 / 12, "status": "partial",
    }
    assert any("do not cover all" in text for text in result["limitations"])
    with rasterio.open(output) as artifact:
        assert np.ma.getmaskarray(artifact.read(1, masked=True))[:, 2:4].all()


def test_explicit_dataset_mask_and_declared_nodata_both_apply(tmp_path):
    tile = write_tile(tmp_path, "masked", [[1, -9999], [3, 4]], nodata=-9999,
                      mask=[[True, True], [False, True]])
    result = analyze_raster_tiles([tile], (0, 0, 2, 2))
    assert result["statistics"]["count"] == 2
    assert result["statistics"]["mean"] == 2.5


def test_source_scale_and_offset_apply_before_hand_range_validation(tmp_path):
    tile = write_tile(tmp_path, "scaled", [[0, 1], [2, 3]], scale=2, offset=-2, unit="m")
    result = analyze_raster_tiles([tile], (0, 0, 2, 2), kind="hand")
    assert result["statistics"]["count"] == 3
    assert result["statistics"]["min"] == 0
    assert result["statistics"]["max"] == 4
    assert result["statistics"]["mean"] == 2


def test_projected_grid_selects_centers_in_wgs84_aoi(tmp_path):
    tile = write_tile(
        tmp_path, "mercator", np.arange(16).reshape(4, 4), crs="EPSG:3857",
        transform=from_origin(0, 300_000, 100_000, 100_000),
    )
    result = analyze_raster_tiles([tile], (0, 0, 2, 2))
    assert result["statistics"] == {
        "units": "m", "min": 4, "max": 9, "mean": 6.5, "median": 6.5, "count": 4,
    }
    assert result["raster"]["crs"] == "EPSG:3857"
    assert result["coverage"]["aoi_pixels"] == 4
    assert result["coverage"]["status"] == "complete"


def test_curved_projected_aoi_excludes_cells_inside_only_its_bounding_rectangle(tmp_path):
    tile = write_tile(
        tmp_path, "polar", np.arange(16).reshape(4, 4), crs="EPSG:3413",
        transform=from_origin(-2_000_000, 2_000_000, 1_000_000, 1_000_000),
    )
    # On this polar grid, only the two central cells in the bottom row lie
    # between longitudes -89 and -1. The enclosing projected rectangle also
    # contains other source cells which must not enter the statistics.
    result = analyze_raster_tiles([tile], (-89, 60, -1, 89))
    assert result["statistics"]["count"] == 2
    assert result["statistics"]["min"] == 13
    assert result["statistics"]["max"] == 14
    assert result["statistics"]["mean"] == 13.5


@pytest.mark.parametrize("bbox", [
    (2, 0, 1, 2), (0, 2, 2, 1), (-181, 0, 1, 2), (0, 0, 1, 91),
    (0, 0, 0, 2), (0, 0, np.nan, 2), (0, 0, np.inf, 2), (0, 0, 1),
    "0123", None, (False, 0, 1, 2),
])
def test_invalid_bbox_is_rejected_before_source_access(bbox):
    with pytest.raises(TerrainProcessingError, match="bbox"):
        validate_bbox(bbox)


@pytest.mark.parametrize("change,match", [
    ({"crs": None}, "no declared CRS"),
    ({"crs": "EPSG:3857"}, "mixed CRS"),
    ({"transform": from_origin(2, 2, 0.5, 1)}, "resolutions"),
    ({"west": 2.25}, "alignment"),
    ({"transform": Affine(1, 0.1, 2, 0, -1, 2)}, "north-up"),
    ({"unit": "ft"}, "units"),
])
def test_incompatible_rasters_fail_instead_of_silent_resampling(tmp_path, change, match):
    first = write_tile(tmp_path, "a", np.ones((2, 2)))
    second = write_tile(tmp_path, "b", np.ones((2, 2)), **change)
    with pytest.raises(TerrainProcessingError, match=match):
        analyze_raster_tiles([first, second], (0, 0, 4, 2))


def test_empty_nonintersecting_and_all_invalid_sources_raise(tmp_path):
    valid = write_tile(tmp_path, "valid", np.ones((2, 2)))
    invalid = write_tile(tmp_path, "invalid", np.full((2, 2), np.nan))
    for tiles, bbox in [([], (0, 0, 2, 2)), ([valid], (10, 10, 12, 12)),
                        ([invalid], (0, 0, 2, 2)), ([valid], (0.1, 0.1, 0.2, 0.2))]:
        with pytest.raises(TerrainProcessingError):
            analyze_raster_tiles(tiles, bbox)


def test_size_cap_and_all_reads_use_only_aoi_window(tmp_path, monkeypatch):
    tile = write_tile(tmp_path, "large", np.ones((100, 100)), north=50)
    original_open = rasterio.open
    reads = []

    class TrackReads:
        def __init__(self, source):
            self.source = source

        def __getattr__(self, name):
            return getattr(self.source, name)

        def __enter__(self):
            self.source.__enter__()
            return self

        def __exit__(self, *args):
            return self.source.__exit__(*args)

        def read(self, *args, **kwargs):
            reads.append(kwargs.get("window"))
            return self.source.read(*args, **kwargs)

    monkeypatch.setattr(_raster.rasterio, "open", lambda *args, **kwargs: TrackReads(original_open(*args, **kwargs)))
    with pytest.raises(TerrainProcessingError, match="max_pixels"):
        analyze_raster_tiles([tile], (0, 0, 50, 50), max_pixels=10)
    assert reads == []
    analyze_raster_tiles([tile], (1, 1, 3, 3), max_pixels=4)
    assert len(reads) == 1
    assert reads[0].width == reads[0].height == 2


def test_duplicate_tile_input_is_not_double_counted_and_conflicts_rejected(tmp_path):
    tile = write_tile(tmp_path, "single", [[1, 2], [3, 4]])
    result = analyze_raster_tiles([tile, tile], (0, 0, 2, 2))
    assert len(result["source_tiles"]) == 1
    assert result["statistics"]["count"] == 4
    with pytest.raises(TerrainProcessingError, match="same terrain tile ID"):
        analyze_raster_tiles([tile, RasterTile(tile.tile_id, "different.tif")], (0, 0, 2, 2))


def test_output_cannot_overwrite_source(tmp_path):
    tile = write_tile(tmp_path, "source", [[1, 2], [3, 4]])
    with pytest.raises(TerrainProcessingError, match="overwrite"):
        analyze_raster_tiles([tile], (0, 0, 2, 2), output_path=tile.href)
    with rasterio.open(tile.href) as source:
        np.testing.assert_array_equal(source.read(1), [[1, 2], [3, 4]])


def test_output_cannot_overwrite_file_uri_source(tmp_path):
    tile = write_tile(tmp_path, "source", [[1, 2], [3, 4]])
    uri_tile = RasterTile(tile.tile_id, Path(tile.href).as_uri())
    with pytest.raises(TerrainProcessingError, match="overwrite"):
        analyze_raster_tiles([uri_tile], (0, 0, 2, 2), output_path=tile.href)
    with rasterio.open(tile.href) as source:
        np.testing.assert_array_equal(source.read(1), [[1, 2], [3, 4]])


def test_provenance_removes_url_secrets(tmp_path, monkeypatch):
    tile = write_tile(tmp_path, "source", [[1, 2], [3, 4]])
    original_open = rasterio.open
    monkeypatch.setattr(_raster.rasterio, "open", lambda *_args, **_kwargs: original_open(tile.href))
    result = analyze_raster_tiles([
        RasterTile("public-id", "https://user:password@example.test/tile.tif?token=secret#secret"),
    ], (0, 0, 2, 2))
    assert result["source_tiles"][0]["href"] == "https://example.test/tile.tif"
    assert "secret" not in json.dumps(result)
    assert "password" not in json.dumps(result)


def test_io_errors_do_not_expose_signed_urls(monkeypatch):
    def fail_open(*args, **kwargs):
        raise OSError("Access denied for https://example.test/tile?secret=password")

    monkeypatch.setattr(_raster.rasterio, "open", fail_open)
    with pytest.raises(TerrainProcessingError) as caught:
        analyze_raster_tiles([RasterTile("tile", "https://example.test/tile?secret=password")], (0, 0, 2, 2))
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("max_pixels", [0, -1, 1.5, True])
def test_invalid_pixel_cap(tmp_path, max_pixels):
    tile = write_tile(tmp_path, "source", [[1]])
    with pytest.raises(TerrainProcessingError, match="max_pixels"):
        analyze_raster_tiles([tile], (0, 0, 2, 2), max_pixels=max_pixels)
