"""Offline HAND catalog and local-raster tests; no external data required."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pystac
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.workers.flood import hand
from backend.workers.flood._raster import RasterTile, TerrainProcessingError


BBOX = (-122.45, 48.95, -121.95, 49.30)
TILE_ID = "Copernicus_DSM_COG_10_N49_00_W123_00_HAND"


def item(tile_id=TILE_ID, href=None, assets=None):
    if assets is None:
        assets = {} if href is None else {"data": pystac.Asset(href, roles=["data"])}
    return SimpleNamespace(id=tile_id, assets=assets)


def mock_catalog(monkeypatch, items):
    catalog = Mock()
    catalog.search.return_value.items.return_value = iter(items)
    catalog.get_collection.return_value.get_item.return_value = None
    opened = Mock(return_value=catalog)
    monkeypatch.setattr(hand.Client, "open", opened)
    return catalog, opened


def test_search_follows_every_page_without_ten_item_truncation(monkeypatch):
    items = [
        item(f"Copernicus_DSM_COG_10_N49_00_E{lon:03d}_00_HAND", f"https://data/{lon}.tif")
        for lon in range(12)
    ]
    catalog, opened = mock_catalog(monkeypatch, reversed(items))

    tiles = hand.discover_hand_tiles((0.1, 49.1, 11.9, 49.5))

    assert len(tiles) == 12
    assert [tile.tile_id for tile in tiles] == sorted(entry.id for entry in items)
    assert catalog.search.call_args.kwargs["max_items"] is None
    assert catalog.search.call_args.kwargs["collections"] == [hand.HAND_COLLECTION]
    assert opened.call_args.kwargs["stac_io"].timeout == (10, 30)
    assert all(tile.collection == hand.HAND_COLLECTION for tile in tiles)


def test_missing_assets_refetched_then_each_tile_uses_public_fallback(monkeypatch):
    first = item()
    second = item("Copernicus_DSM_COG_10_N49_00_W122_00_HAND")
    catalog, _ = mock_catalog(monkeypatch, [first, second])

    tiles = hand.discover_hand_tiles(BBOX)

    assert len(tiles) == 2
    assert {tile.href for tile in tiles} == {
        f"{hand.HAND_S3_BASE}/{entry.id}.tif" for entry in [first, second]
    }
    assert catalog.get_collection.return_value.get_item.call_count == 2


def test_full_item_data_asset_preferred_to_s3_fallback(monkeypatch):
    catalog, _ = mock_catalog(monkeypatch, [item()])
    catalog.get_collection.return_value.get_item.return_value = item(href="https://data/hand.tif")

    assert hand.discover_hand_tiles(BBOX)[0].href == "https://data/hand.tif"


def test_refetch_failure_still_uses_verified_public_tile_id(monkeypatch):
    catalog, _ = mock_catalog(monkeypatch, [item()])
    catalog.get_collection.return_value.get_item.side_effect = RuntimeError("Unavailable")

    assert hand.discover_hand_tiles(BBOX)[0].href.endswith(f"/{TILE_ID}.tif")


def test_geotiff_query_and_data_roles_are_respected(monkeypatch):
    assets = {
        "preview": pystac.Asset("https://data/preview.tif", roles=["thumbnail"]),
        "height": pystac.Asset("https://data/height.tif?access=temporary", roles=["data"]),
        "aux": pystac.Asset("https://data/aux.tif"),
    }
    mock_catalog(monkeypatch, [item(assets=assets)])

    assert hand.discover_hand_tiles(BBOX)[0].href == "https://data/height.tif?access=temporary"


@pytest.mark.parametrize("tile_id", ["../secret", "arbitrary", "Copernicus_DSM_COG_10_N90_00_E190_00_HAND"])
def test_undocumented_or_out_of_range_ids_are_never_guessed(monkeypatch, tile_id):
    mock_catalog(monkeypatch, [item(tile_id)])

    with pytest.raises(TerrainProcessingError):
        hand.discover_hand_tiles(BBOX)


def test_search_failure_never_returns_partial_results_or_exposes_credentials(monkeypatch):
    def interrupted_pages():
        yield item()
        raise RuntimeError("https://private/?token=SECRET")

    mock_catalog(monkeypatch, interrupted_pages())

    with pytest.raises(TerrainProcessingError, match="Could not search") as error:
        hand.discover_hand_tiles(BBOX)
    assert "SECRET" not in str(error.value)
    assert error.value.__suppress_context__


def test_empty_search_is_explicit_failure(monkeypatch):
    mock_catalog(monkeypatch, [])

    with pytest.raises(TerrainProcessingError, match="No HAND tiles"):
        hand.discover_hand_tiles(BBOX)


def test_oversized_catalog_response_raises_instead_of_truncating(monkeypatch):
    mock_catalog(monkeypatch, [item()] * 257)

    with pytest.raises(TerrainProcessingError, match="256-tile"):
        hand.discover_hand_tiles(BBOX)


def test_identical_catalog_duplicates_are_removed(monkeypatch):
    mock_catalog(monkeypatch, [item(href="https://data/hand.tif")] * 2)

    assert len(hand.discover_hand_tiles(BBOX)) == 1


def test_conflicting_catalog_duplicates_raise(monkeypatch):
    mock_catalog(monkeypatch, [item(href="https://data/a.tif"), item(href="https://data/b.tif")])

    with pytest.raises(TerrainProcessingError, match="conflicting"):
        hand.discover_hand_tiles(BBOX)


def test_invalid_bbox_rejected_before_network(monkeypatch):
    _, opened = mock_catalog(monkeypatch, [])

    with pytest.raises(TerrainProcessingError):
        hand.discover_hand_tiles((10, 49, -10, 50))
    opened.assert_not_called()


def test_local_hand_processing_keeps_zero_and_masks_invalid_values(tmp_path):
    path = tmp_path / "hand.tif"
    output = tmp_path / "aoi.tif"
    data = np.array([[0, 1, -1], [10, np.nan, 9999]], dtype="float32")
    with rasterio.open(
        path, "w", driver="GTiff", height=2, width=3, count=1,
        dtype="float32", crs="EPSG:4326", nodata=9999,
        transform=from_origin(-123, 49, 0.1, 0.1),
    ) as dataset:
        dataset.write(data, 1)

    result = hand.analyze_hand_tiles(
        [RasterTile("local-hand", str(path), hand.HAND_COLLECTION)],
        (-123, 48.8, -122.7, 49),
        output_path=output,
    )

    assert result["kind"] == "hand"
    assert result["statistics"]["count"] == 3
    assert result["statistics"]["min"] == 0
    assert result["statistics"]["max"] == 10
    assert result["statistics"]["mean"] == pytest.approx(11 / 3)
    assert result["source_tiles"][0]["tile_id"] == "local-hand"
    assert any("does not detect floodwater" in limitation for limitation in result["limitations"])
    with rasterio.open(output) as artifact:
        assert artifact.read(1, masked=True).count() == 3


def test_analyze_hand_connects_discovery_to_processing(monkeypatch):
    tiles = [RasterTile(TILE_ID, "https://data/hand.tif", hand.HAND_COLLECTION)]
    discovered = Mock(return_value=tiles)
    processed = Mock(return_value={"kind": "hand"})
    monkeypatch.setattr(hand, "discover_hand_tiles", discovered)
    monkeypatch.setattr(hand, "analyze_hand_tiles", processed)

    assert hand.analyze_hand(BBOX, output_path="aoi.tif") == {"kind": "hand"}
    discovered.assert_called_once_with(BBOX)
    processed.assert_called_once_with(tiles, BBOX, output_path="aoi.tif")
