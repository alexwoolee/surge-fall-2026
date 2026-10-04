"""DEM discovery must retain all tiles and fail explicitly on incomplete metadata."""

from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.workers.flood import terrain
from backend.workers.flood.hand import analyze_hand_tiles
from backend.workers.flood._raster import RasterTile, TerrainProcessingError

BBOX = (0, 0, 2, 1)


def item(tile_id, href="https://example.test/tile.tif"):
    return SimpleNamespace(id=tile_id, assets={"data": SimpleNamespace(href=href)})


def mock_catalog(monkeypatch, items):
    calls = {}

    def search(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(items=lambda: iter(items))

    monkeypatch.setattr(terrain.Client, "open", lambda *args, **kwargs: SimpleNamespace(search=search))
    return calls


def test_discovery_keeps_all_pages_and_orders_tiles(monkeypatch):
    calls = mock_catalog(monkeypatch, [item(f"tile-{i:02}") for i in range(14, -1, -1)])
    tiles = terrain.discover_dem_tiles(BBOX)
    assert len(tiles) == 15  # The previous smoke test read at most ten hits.
    assert [tile.tile_id for tile in tiles] == [f"tile-{i:02}" for i in range(15)]
    assert "max_items" not in calls
    assert calls["collections"] == ["cop-dem-glo-30"]


@pytest.mark.parametrize("items, message", [
    ([], "No Copernicus"),
    ([SimpleNamespace(id="missing", assets={})], "no data asset"),
    ([item("duplicate", "a"), item("duplicate", "b")], "Conflicting"),
    ([item(str(i)) for i in range(129)], "exceeds"),
])
def test_bad_discovery_fails_instead_of_partial_success(monkeypatch, items, message):
    mock_catalog(monkeypatch, items)
    with pytest.raises(TerrainProcessingError, match=message):
        terrain.discover_dem_tiles(BBOX)


def test_network_error_does_not_expose_signed_url(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("https://example.test/tile?secret=token")
    monkeypatch.setattr(terrain.Client, "open", fail)
    with pytest.raises(TerrainProcessingError) as exc:
        terrain.discover_dem_tiles(BBOX)
    assert "secret" not in str(exc.value)


def test_local_dem_wrapper_runs_actual_raster_processor(tmp_path):
    tiles = []
    for index, values in enumerate([[-2, 0], [10, 20]]):
        path = tmp_path / f"tile{index}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=1, height=2,
                           count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_origin(index, 1, 1, 0.5)) as dst:
            dst.write(np.array(values, dtype="float32").reshape(2, 1), 1)
        tiles.append(RasterTile(str(index), str(path), "cop-dem-glo-30"))
    result = terrain.analyze_dem_tiles(tiles, BBOX)
    assert result["statistics"]["count"] == 4
    assert result["statistics"]["mean"] == 7
    assert result["statistics"]["min"] == -2
    assert result["coverage"]["status"] == "complete"
    assert len(result["source_tiles"]) == 2


@pytest.mark.parametrize("analyze", [terrain.analyze_dem_tiles, analyze_hand_tiles])
def test_wrappers_honor_external_mask_files(tmp_path, analyze):
    path = tmp_path / "masked.tif"
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(path, "w", driver="GTiff", width=2, height=2,
                           count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_origin(0, 1, 0.5, 0.5)) as dst:
            dst.write(np.array([[100, 1], [2, 3]], dtype="float32"), 1)
            dst.write_mask(np.array([[0, 255], [255, 255]], dtype="uint8"))
    assert path.with_suffix(".tif.msk").exists()
    result = analyze([RasterTile("masked", str(path))], (0, 0, 1, 1))
    assert result["statistics"]["count"] == 3
    assert result["statistics"]["mean"] == 2
    assert result["coverage"]["valid_fraction"] == 0.75
