"""Offline Sentinel-1 contracts against synthetic, calibrated UTM rasters.

Expected pixel counts and areas are deliberately hand-computable. These tests
exercise the scientific boundary (linear power -> dB -> candidates), coverage,
and source validation without contacting a catalog or downloading SAR data.
"""

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin
from rasterio.warp import transform_bounds

from backend.workers.flood import sentinel1
from backend.workers.flood.sentinel1 import (
    Sentinel1ProcessingError,
    Sentinel1Scene,
    analyze_sentinel1_scene,
    discover_sentinel1_scene,
    select_scene,
)

CRS = "EPSG:32631"
GRID = from_origin(500_000, 40, 10, 10)
ACQUIRED = "2021-11-15T14:00:00Z"
START = "2021-11-13T00:00:00Z"
END = "2021-11-18T23:59:59Z"


def grid_bbox(width=4, height=4, *, grid=GRID):
    west, north = grid @ (0, 0)
    east, south = grid @ (width, height)
    return transform_bounds(CRS, "EPSG:4326", west, south, east, north, densify_pts=128)


def write_scene(tmp_path, data, *, name="scene", dtype="float32", crs=CRS,
                grid=GRID, nodata=None, mask=None, scale=1, offset=0, count=1):
    values = np.asarray(data, dtype=dtype)
    path = tmp_path / f"{name}.tif"
    # Force an external mask to guard against ignoring the .msk sidecar.
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(
            path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
            count=count, dtype=dtype, crs=crs, transform=grid, nodata=nodata,
        ) as target:
            for band in range(1, count + 1):
                target.write(values, band)
            target.scales = (scale,) * count
            target.offsets = (offset,) * count
            if mask is not None:
                target.write_mask(np.asarray(mask, dtype="uint8") * 255)
    return Sentinel1Scene(
        scene_id=name, href=str(path), acquired_at=ACQUIRED,
        bbox=grid_bbox(values.shape[1], values.shape[0], grid=grid),
        orbit_state="descending", relative_orbit=42,
    )


def test_linear_power_conversion_inclusive_threshold_and_planimetric_area(tmp_path):
    scene = write_scene(tmp_path, [[0.01, 0.1], [1, 10]])
    result = analyze_sentinel1_scene(scene, grid_bbox(2, 2), threshold_db=0)
    stats = result["backscatter_db"]
    assert stats["units"] == "dB"
    assert stats["count"] == 4
    assert stats["min"] == pytest.approx(-20)
    assert stats["max"] == pytest.approx(10)
    assert stats["mean"] == pytest.approx(-5)
    assert stats["median"] == pytest.approx(-5)
    assert result["candidate_water"] == {
        "count": 3, "fraction_valid": 0.75, "area_km2": 0.0003,
    }
    assert result["raster"]["pixel_area_m2"] == 100
    assert result["raster"]["crs"] == CRS
    assert result["method"]["threshold_db"] == 0
    assert result["method"]["comparison"] == "<="
    assert result["method"]["smoothing"].startswith("none")
    assert result["coverage"] == {
        "aoi_pixels": 4, "covered_pixels": 4, "valid_pixels": 4,
        "coverage_fraction": 1, "valid_fraction": 1, "status": "complete",
    }
    assert result["artifacts"] is None
    json.dumps(result, allow_nan=False)


def test_positive_finite_values_mask_and_nodata_are_all_required(tmp_path):
    scene = write_scene(
        tmp_path, [[0.01, 0.1, 1, 0, -0.1], [np.nan, np.inf, -32768, 0.001, 0]],
        nodata=-32768, mask=[[1, 1, 1, 1, 1], [1, 1, 1, 0, 1]],
    )
    assert Path(scene.href + ".msk").exists()
    result = analyze_sentinel1_scene(scene, grid_bbox(5, 2), threshold_db=-17)
    assert result["backscatter_db"]["count"] == 3
    assert result["backscatter_db"]["mean"] == pytest.approx(-10)
    assert result["candidate_water"]["count"] == 1
    assert result["candidate_water"]["fraction_valid"] == pytest.approx(1 / 3)
    assert result["candidate_water"]["area_km2"] == 0.0001
    assert result["coverage"] == {
        "aoi_pixels": 10, "covered_pixels": 10, "valid_pixels": 3,
        "coverage_fraction": 1, "valid_fraction": 0.3, "status": "partial",
    }


def test_aoi_uses_pixel_centers_in_original_wgs84_bbox(tmp_path):
    scene = write_scene(tmp_path, np.arange(1, 17).reshape(4, 4))
    # This rectangle spans native coordinates 500006..500034 / 6..34;
    # exactly four centers (15,15), (25,15), (15,25), (25,25) are inside.
    bbox = transform_bounds(CRS, "EPSG:4326", 500_006, 6, 500_034, 34)
    result = analyze_sentinel1_scene(scene, bbox, threshold_db=0)
    expected = 10 * np.log10([6, 7, 10, 11])
    assert result["backscatter_db"]["count"] == 4
    assert result["coverage"]["aoi_pixels"] == 4
    assert result["backscatter_db"]["mean"] == pytest.approx(expected.mean())
    assert result["candidate_water"]["count"] == 0


def test_partial_scene_coverage_keeps_whole_aoi_as_denominator(tmp_path):
    scene = write_scene(tmp_path, np.full((2, 2), 0.01))
    result = analyze_sentinel1_scene(scene, grid_bbox(4, 2))
    assert result["coverage"] == {
        "aoi_pixels": 8, "covered_pixels": 4, "valid_pixels": 4,
        "coverage_fraction": 0.5, "valid_fraction": 0.5, "status": "partial",
    }
    assert result["candidate_water"]["count"] == 4
    assert result["candidate_water"]["fraction_valid"] == 1
    assert result["candidate_water"]["area_km2"] == 0.0004
    assert any("cover" in limitation.lower() for limitation in result["limitations"])


def test_saved_artifacts_reproduce_counts_and_preserve_invalid_cells(tmp_path):
    scene = write_scene(tmp_path, [[0.01, 1], [0, -32768]], nodata=-32768)
    result = analyze_sentinel1_scene(
        scene, grid_bbox(4, 2), output_dir=tmp_path / "output",
    )
    with rasterio.open(result["artifacts"]["backscatter_db"]) as db:
        backscatter = db.read(1, masked=True)
        assert db.dtypes == ("float64",)
        assert np.isnan(db.nodata)
        assert db.crs.to_string() == CRS
        assert db.units == ("dB",)
        assert backscatter.count() == result["backscatter_db"]["count"] == 2
        assert backscatter.min() == pytest.approx(-20)
        assert backscatter.max() == 0
        assert backscatter.mean() == result["backscatter_db"]["mean"]
        saved_transform, saved_shape = db.transform, db.shape
    with rasterio.open(result["artifacts"]["candidate_water"]) as mask:
        water = mask.read(1)
        assert mask.dtypes == ("uint8",)
        assert mask.nodata == 255
        assert mask.crs.to_string() == CRS
        assert mask.transform == saved_transform
        assert mask.shape == saved_shape
        assert np.count_nonzero(water == 1) == result["candidate_water"]["count"] == 1
        assert np.count_nonzero(water == 0) == 1
        assert np.count_nonzero(water != 255) == 2
        assert np.count_nonzero(water == 255) == water.size - 2
        np.testing.assert_array_equal(water == 255, np.ma.getmaskarray(backscatter))


def test_sensitivity_counts_are_monotonic_and_use_same_valid_pixels(tmp_path):
    scene = write_scene(tmp_path, [[0.01, 0.018, 0.025, 0.1]])
    result = analyze_sentinel1_scene(scene, grid_bbox(4, 1))
    assert [entry["threshold_db"] for entry in result["sensitivity"]] == [-19, -17, -15]
    assert [entry["count"] for entry in result["sensitivity"]] == [1, 2, 3]
    assert [entry["fraction_valid"] for entry in result["sensitivity"]] == [0.25, 0.5, 0.75]
    assert result["candidate_water"]["count"] == 2


def test_repeat_processing_has_identical_payload(tmp_path):
    scene = write_scene(tmp_path, [[0.01, 0.1], [1, 10]])
    first = analyze_sentinel1_scene(scene, grid_bbox(2, 2))
    second = analyze_sentinel1_scene(scene, grid_bbox(2, 2))
    assert first == second
    assert first["scene"]["acquired_at"] == ACQUIRED
    assert first["scene"]["orbit_state"] == "descending"
    assert first["scene"]["relative_orbit"] == 42
    assert any("flood" in text.lower() for text in first["limitations"])


@pytest.mark.parametrize("values", [[[0, -1]], [[np.nan, np.inf]], [[-32768, -32768]]])
def test_no_valid_backscatter_fails(tmp_path, values):
    scene = write_scene(tmp_path, values, nodata=-32768)
    with pytest.raises(Sentinel1ProcessingError):
        analyze_sentinel1_scene(scene, grid_bbox(2, 1))


def test_nonintersecting_aoi_and_aoi_without_centers_fail(tmp_path):
    scene = write_scene(tmp_path, [[0.1, 0.2], [0.3, 0.4]])
    tiny = transform_bounds(CRS, "EPSG:4326", 500_000.1, 39, 500_001, 39.9)
    for bbox in [(4, 0, 4.001, 0.001), tiny]:
        with pytest.raises(Sentinel1ProcessingError):
            analyze_sentinel1_scene(scene, bbox)


@pytest.mark.parametrize("change", [
    {"dtype": "uint16"}, {"crs": None}, {"crs": "EPSG:4326"},
    {"crs": "EPSG:3857"}, {"scale": 2}, {"offset": 1}, {"count": 2},
    {"grid": Affine(10, 1, 500_000, 0, -10, 40)},
])
def test_unsupported_raster_metadata_is_rejected(tmp_path, change):
    scene = write_scene(tmp_path, [[1, 2], [3, 4]], **change)
    with pytest.raises(Sentinel1ProcessingError):
        analyze_sentinel1_scene(scene, grid_bbox(2, 2))


@pytest.mark.parametrize("change", [
    {"collection": "sentinel-1-grd"}, {"polarization": "VH"},
    {"scene_id": ""}, {"href": ""}, {"acquired_at": "not-a-date"},
    {"acquired_at": "2021-11-15T14:00:00"}, {"bbox": (0, 0, 0, 1)},
])
def test_scene_contract_rejects_raw_grd_wrong_polarization_and_missing_metadata(tmp_path, change):
    scene = replace(write_scene(tmp_path, [[0.1]]), **change)
    with pytest.raises(Sentinel1ProcessingError):
        analyze_sentinel1_scene(scene, grid_bbox(1, 1))


@pytest.mark.parametrize("bbox", [
    None, (0, 0, 1), (0, 0, np.nan, 1), (1, 0, 0, 1),
    (0, 0, 1, 91), (-181, 0, 1, 1), (False, 0, 1, 1),
])
def test_invalid_bbox_is_rejected_before_opening_source(tmp_path, monkeypatch, bbox):
    scene = write_scene(tmp_path, [[0.1]])
    opened = Mock(side_effect=AssertionError("Invalid bbox must fail before source access"))
    monkeypatch.setattr(sentinel1.rasterio, "open", opened)
    with pytest.raises(Sentinel1ProcessingError):
        analyze_sentinel1_scene(scene, bbox)
    opened.assert_not_called()


@pytest.mark.parametrize("threshold", [np.nan, np.inf, -np.inf, True, "-17", None, -41, 1])
def test_invalid_threshold_is_rejected(tmp_path, threshold):
    scene = write_scene(tmp_path, [[0.1]])
    with pytest.raises(Sentinel1ProcessingError):
        analyze_sentinel1_scene(scene, grid_bbox(1, 1), threshold_db=threshold)


@pytest.mark.parametrize("max_pixels", [0, -1, 1.5, True])
def test_invalid_pixel_limit(tmp_path, max_pixels):
    scene = write_scene(tmp_path, [[0.1]])
    with pytest.raises(Sentinel1ProcessingError):
        analyze_sentinel1_scene(scene, grid_bbox(1, 1), max_pixels=max_pixels)


def test_pixel_cap_precedes_data_reads_and_reads_are_windowed(tmp_path, monkeypatch):
    scene = write_scene(tmp_path, np.full((100, 100), 0.1))
    original_open = rasterio.open
    reads = []

    class TrackedSource:
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

    monkeypatch.setattr(sentinel1.rasterio, "open", lambda *a, **kw: TrackedSource(original_open(*a, **kw)))
    with pytest.raises(Sentinel1ProcessingError, match="max_pixels"):
        analyze_sentinel1_scene(scene, grid_bbox(100, 100), max_pixels=10)
    assert reads == []
    analyze_sentinel1_scene(scene, grid_bbox(2, 2), max_pixels=25)
    assert len(reads) == 1
    assert reads[0] is not None
    assert reads[0].width <= 4
    assert reads[0].height <= 4


def test_provenance_strips_url_credentials_and_query_tokens(tmp_path, monkeypatch):
    local = write_scene(tmp_path, [[0.1]])
    original_open = rasterio.open
    monkeypatch.setattr(sentinel1.rasterio, "open", lambda *a, **kw: original_open(local.href))
    scene = replace(local, href="https://username:password@example.test/a.tif?token=secret#secret")
    result = analyze_sentinel1_scene(scene, grid_bbox(1, 1))
    assert result["scene"]["href"] == "https://example.test/a.tif"
    assert "secret" not in json.dumps(result)
    assert "password" not in json.dumps(result)


def test_io_errors_redact_provider_urls_and_exception_context(tmp_path, monkeypatch):
    scene = write_scene(tmp_path, [[0.1]])
    monkeypatch.setattr(sentinel1.rasterio, "open", Mock(side_effect=OSError("https://example.test/?secret=token")))
    with pytest.raises(Sentinel1ProcessingError) as caught:
        analyze_sentinel1_scene(scene, grid_bbox(1, 1))
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__


def make_scene(scene_id, *, bbox=(0, 0, 2, 2), acquired_at=ACQUIRED, href=None):
    return Sentinel1Scene(scene_id, href or f"https://example.test/{scene_id}.tif", acquired_at, bbox)


def test_selection_prioritizes_coverage_then_time_then_stable_id():
    near_partial = make_scene("partial", bbox=(0, 0, 1, 2))
    far_full = make_scene("far", acquired_at="2021-11-13T14:00:00Z")
    close_full_b = make_scene("b", acquired_at="2021-11-15T13:00:00Z")
    close_full_a = make_scene("a", acquired_at="2021-11-15T15:00:00Z")
    scenes = [near_partial, close_full_b, far_full, close_full_a]
    for order in (scenes, list(reversed(scenes))):
        assert select_scene(order, (0, 0, 2, 2), ACQUIRED).scene_id == "a"
    assert select_scene([near_partial, far_full], (0, 0, 2, 2), ACQUIRED).scene_id == "far"


def test_selection_accepts_aware_datetime_and_ignores_nonintersecting_scenes():
    missing = make_scene("missing", bbox=(10, 10, 12, 12))
    valid = make_scene("valid", acquired_at=datetime(2021, 11, 15, 14, tzinfo=timezone.utc))
    assert select_scene([missing, valid], (0, 0, 2, 2), ACQUIRED).scene_id == "valid"


def test_identical_duplicate_scenes_are_deduplicated_but_conflicts_fail():
    scene = make_scene("same")
    assert select_scene([scene, scene], (0, 0, 2, 2), ACQUIRED).scene_id == "same"
    with pytest.raises(Sentinel1ProcessingError):
        select_scene([scene, replace(scene, href="https://example.test/other.tif")], (0, 0, 2, 2), ACQUIRED)


@pytest.mark.parametrize("scenes", [[], [make_scene("outside", bbox=(10, 10, 12, 12))]])
def test_selection_fails_for_no_usable_scenes(scenes):
    with pytest.raises(Sentinel1ProcessingError):
        select_scene(scenes, (0, 0, 2, 2), ACQUIRED)


def catalog_item(scene_id, *, acquired_at=ACQUIRED, bbox=(0, 0, 2, 2),
                 collection="sentinel-1-rtc", polarizations=None, assets=None):
    return SimpleNamespace(
        id=scene_id, collection_id=collection, bbox=list(bbox),
        datetime=datetime.fromisoformat(acquired_at.replace("Z", "+00:00")),
        properties={"datetime": acquired_at, "sar:polarizations": polarizations or ["VV", "VH"],
                    "sat:orbit_state": "descending", "sat:relative_orbit": 42},
        assets={"vv": SimpleNamespace(href=f"https://example.test/{scene_id}.tif")} if assets is None else assets,
    )


def mock_catalog(monkeypatch, items):
    catalog = Mock()
    catalog.search.return_value.items.return_value = iter(items)
    opened = Mock(return_value=catalog)
    monkeypatch.setattr(sentinel1.Client, "open", opened)
    return catalog, opened


def test_discovery_examines_all_pages_and_selects_best_scene(monkeypatch):
    # The only complete-coverage result occurs beyond the first ten items.
    items = [catalog_item(f"partial-{i}", bbox=(0, 0, 1, 2)) for i in range(12)]
    items.append(catalog_item("complete"))
    catalog, opened = mock_catalog(monkeypatch, items)
    result = discover_sentinel1_scene((0, 0, 2, 2), START, END, reference_time=ACQUIRED)
    assert result.scene_id == "complete"
    kwargs = catalog.search.call_args.kwargs
    assert kwargs["collections"] == ["sentinel-1-rtc"]
    assert "max_items" not in kwargs
    assert kwargs["datetime"] == f"{START}/{END}"
    assert opened.call_count == 1


@pytest.mark.parametrize("items", [
    [], [catalog_item("missing", assets={})],
    [catalog_item("wrong-polarization", polarizations=["VH"])],
    [catalog_item("raw-grd", collection="sentinel-1-grd")],
    [catalog_item(str(i)) for i in range(129)],
])
def test_invalid_discovery_never_silently_returns_partial_success(monkeypatch, items):
    mock_catalog(monkeypatch, items)
    with pytest.raises(Sentinel1ProcessingError):
        discover_sentinel1_scene((0, 0, 2, 2), START, END)


@pytest.mark.parametrize("start,end,reference", [
    (END, START, ACQUIRED), ("bad", END, ACQUIRED),
    ("2021-11-13T00:00:00", END, ACQUIRED), (START, END, "bad"),
])
def test_invalid_discovery_dates_fail_before_network(monkeypatch, start, end, reference):
    opened = Mock(side_effect=AssertionError("Invalid dates must not access catalog"))
    monkeypatch.setattr(sentinel1.Client, "open", opened)
    with pytest.raises(Sentinel1ProcessingError):
        discover_sentinel1_scene((0, 0, 2, 2), start, end, reference_time=reference)
    opened.assert_not_called()


def test_catalog_error_redacts_signed_urls(monkeypatch):
    monkeypatch.setattr(sentinel1.Client, "open", Mock(side_effect=RuntimeError("https://example.test/?secret=token")))
    with pytest.raises(Sentinel1ProcessingError) as caught:
        discover_sentinel1_scene((0, 0, 2, 2), START, END)
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("name", ["backscatter_db", "candidate_water"])
@pytest.mark.parametrize("file_uri", [False, True])
def test_output_cannot_overwrite_source_raster(tmp_path, name, file_uri):
    scene = write_scene(tmp_path, [[0.01, 1]], name=name)
    if file_uri:
        scene = replace(scene, href=Path(scene.href).as_uri())
    with pytest.raises(Sentinel1ProcessingError, match="overwrite"):
        analyze_sentinel1_scene(scene, grid_bbox(2, 1), output_dir=tmp_path)
    with rasterio.open(scene.href) as source:
        np.testing.assert_allclose(source.read(1), [[0.01, 1]])


def test_float64_linear_power_and_rectangular_pixel_area(tmp_path):
    grid = from_origin(500_000, 40, 20, 10)
    scene = write_scene(tmp_path, [[0.01, 0.1]], grid=grid, dtype="float64")
    result = analyze_sentinel1_scene(scene, grid_bbox(2, 1, grid=grid))
    assert result["raster"]["pixel_area_m2"] == 200
    assert result["candidate_water"]["count"] == 1
    assert result["candidate_water"]["area_km2"] == 0.0002
    assert result["backscatter_db"]["min"] == -20


def test_db_input_is_rejected_before_second_log_conversion(tmp_path):
    scene = write_scene(tmp_path, [[-20, -10]])
    with rasterio.open(scene.href, "r+") as source:
        source.set_band_unit(1, "dB")
    with pytest.raises(Sentinel1ProcessingError, match="linear"):
        analyze_sentinel1_scene(scene, grid_bbox(2, 1))


def test_discovery_signs_only_the_selected_azure_asset(monkeypatch):
    def azure_item(scene_id, bbox):
        return catalog_item(scene_id, bbox=bbox, assets={
            "vv": SimpleNamespace(href=f"https://storage.blob.core.windows.net/data/{scene_id}.tif"),
        })

    mock_catalog(monkeypatch, [azure_item("partial", (0, 0, 1, 2)), azure_item("complete", (0, 0, 2, 2))])
    signed = Mock(side_effect=lambda href: href + "?signature=private")
    monkeypatch.setattr(sentinel1.pc, "sign", signed)
    scene = discover_sentinel1_scene((0, 0, 2, 2), START, END)
    assert scene.scene_id == "complete"
    signed.assert_called_once_with("https://storage.blob.core.windows.net/data/complete.tif")
    assert scene.href.endswith("?signature=private")


def test_discovery_default_reference_is_the_search_interval_midpoint(monkeypatch):
    early = catalog_item("early", acquired_at="2021-11-13T12:00:00Z")
    middle = catalog_item("middle", acquired_at="2021-11-16T00:00:00Z")
    late = catalog_item("late", acquired_at="2021-11-18T00:00:00Z")
    mock_catalog(monkeypatch, [early, late, middle])
    assert discover_sentinel1_scene((0, 0, 2, 2), START, END).scene_id == "middle"


def test_discovery_rejects_provider_scene_outside_requested_dates(monkeypatch):
    mock_catalog(monkeypatch, [catalog_item("wrong-date", acquired_at="2021-11-20T00:00:00Z")])
    with pytest.raises(Sentinel1ProcessingError):
        discover_sentinel1_scene((0, 0, 2, 2), START, END)


def test_discovery_rejects_conflicting_assets_for_duplicate_scene_id(monkeypatch):
    first = catalog_item("duplicate")
    second = catalog_item("duplicate", assets={"vv": SimpleNamespace(href="https://example.test/conflict.tif")})
    mock_catalog(monkeypatch, [first, second])
    with pytest.raises(Sentinel1ProcessingError):
        discover_sentinel1_scene((0, 0, 2, 2), START, END)
