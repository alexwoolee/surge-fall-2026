"""Multi-tile Copernicus GLO-30 elevation processing for Phase 3A.

The approved source is Earth Search's cop-dem-glo-30 collection. Discovery
consumes all search pages; statistics come from the shared bounded raster reader.
"""

from pathlib import Path

import rasterio
from pystac_client import Client

from backend.workers.flood._raster import (
    RasterTile,
    TerrainProcessingError,
    analyze_raster_tiles,
    validate_bbox,
)

STAC_URL = "https://earth-search.aws.element84.com/v1"
DEM_COLLECTION = "cop-dem-glo-30"
MAX_TILES = 128


def discover_dem_tiles(bbox) -> list[RasterTile]:
    """Return every matching DEM tile in stable order; never truncate a mosaic."""
    bbox = validate_bbox(bbox)
    try:
        catalog = Client.open(STAC_URL, timeout=30)
        items = catalog.search(collections=[DEM_COLLECTION], bbox=bbox, limit=100).items()
        tiles = {}
        for item in items:
            asset = item.assets.get("data")
            if asset is None or not asset.href:
                raise TerrainProcessingError(f"DEM tile {item.id} has no data asset.")
            tile = RasterTile(item.id, asset.href, DEM_COLLECTION)
            if item.id in tiles and tiles[item.id].href != tile.href:
                raise TerrainProcessingError(f"Conflicting assets for DEM tile {item.id}.")
            tiles[item.id] = tile
            if len(tiles) > MAX_TILES:
                raise TerrainProcessingError("DEM request exceeds 128 tiles; use a smaller AOI.")
    except TerrainProcessingError:
        raise
    except Exception as exc:
        # Provider errors can contain signed URLs; do not propagate their text.
        raise TerrainProcessingError(f"DEM discovery failed ({type(exc).__name__}).") from None
    if not tiles:
        raise TerrainProcessingError("No Copernicus DEM tiles intersect the requested AOI.")
    return [tiles[key] for key in sorted(tiles)]


def analyze_dem_tiles(tiles, bbox, *, output_path: str | Path | None = None,
                      max_pixels: int = 10_000_000) -> dict:
    """Analyze approved remote assets or explicitly provided local DEM tiles."""
    with rasterio.Env(
        AWS_NO_SIGN_REQUEST="YES", AWS_REGION="eu-central-1",
        GDAL_DISABLE_READDIR_ON_OPEN="TRUE", GDAL_HTTP_TIMEOUT="30",
        GDAL_HTTP_CONNECTTIMEOUT="10", GDAL_HTTP_MAX_RETRY="2",
    ):
        result = analyze_raster_tiles(
            tiles, bbox, kind="dem", output_path=output_path, max_pixels=max_pixels,
        )
    result["source"] = "Copernicus DEM GLO-30"
    result["collection"] = DEM_COLLECTION
    result["limitations"].append(
        "Copernicus DEM is a surface model: buildings and vegetation can influence elevation. "
        "Elevation is referenced to EGM2008, not a local water level."
    )
    return result


def analyze_dem(bbox, *, output_path: str | Path | None = None,
                max_pixels: int = 10_000_000) -> dict:
    return analyze_dem_tiles(
        discover_dem_tiles(bbox), bbox, output_path=output_path, max_pixels=max_pixels,
    )
