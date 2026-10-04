"""Discover and analyze the ASF GLO-30 Height Above Nearest Drainage tiles.

The public fallback uses the tile naming/version documented by ASF:
https://glo-30-hand.s3.amazonaws.com/readme.html

The ASF generation code writes NaN as NoData; some published COGs omit the
NoData metadata. Processing honors raster masks, rejects nonfinite/negative
values, and keeps zero (drainage height). It cannot infer undeclared positive
sentinel values; the raster processor reports this limitation explicitly.
https://hyp3-docs.asf.alaska.edu/tools/asf_tools_api/
"""

from collections.abc import Iterable, Sequence
from pathlib import Path
import re
from urllib.parse import urlsplit

import rasterio
from pystac_client import Client
from pystac_client.stac_api_io import StacApiIO

from ._raster import (
    RasterTile,
    TerrainProcessingError,
    analyze_raster_tiles,
    validate_bbox,
)


STAC_URL = "https://stac.asf.alaska.edu/"
HAND_COLLECTION = "glo-30-hand"
HAND_S3_BASE = "https://glo-30-hand.s3.us-west-2.amazonaws.com/v1/2021"
# A bounded task must either return every tile or fail; never truncate results.
MAX_CATALOG_TILES = 256
_TILE_NAME = re.compile(
    r"Copernicus_DSM_COG_10_([NS])(\d{2})_00_([EW])(\d{3})_00_HAND"
)


def _raster_href(item) -> str | None:
    """Choose a data GeoTIFF deterministically, excluding preview assets."""
    candidates = []
    for key, asset in item.assets.items():
        roles = asset.roles or []
        if "thumbnail" in roles or "overview" in roles:
            continue
        href = asset.get_absolute_href() or asset.href
        if not href:
            continue
        path = urlsplit(href).path.lower()
        media_type = (asset.media_type or "").lower()
        if path.endswith((".tif", ".tiff")) or "tiff" in media_type:
            candidates.append(("data" not in roles, key != "data", key, href))
    return min(candidates)[-1] if candidates else None


def _public_tile_href(tile_id: str) -> str:
    """Resolve only an actual catalog ID matching ASF's documented scheme."""
    match = _TILE_NAME.fullmatch(tile_id)
    if match is None:
        raise TerrainProcessingError(
            "HAND tile metadata has no raster asset and no recognized public tile ID."
        )
    ns, northing, ew, easting = match.groups()
    latitude = int(northing) * (-1 if ns == "S" else 1)
    longitude = int(easting) * (-1 if ew == "W" else 1)
    if not (-90 <= latitude < 90 and -180 <= longitude < 180):
        raise TerrainProcessingError("HAND catalog returned an invalid tile coordinate.")
    return f"{HAND_S3_BASE}/{tile_id}.tif"


def discover_hand_tiles(bbox: Sequence[float]) -> list[RasterTile]:
    """Return every HAND tile intersecting an EPSG:4326 bounding box.

    Pystac follows all search pages. Lightweight ASF items are re-fetched when
    possible, then resolved through the documented public S3 naming scheme if
    their assets remain absent. A failed search raises instead of constructing
    guessed tile names or returning an incomplete subset.
    """
    bounds = validate_bbox(bbox)
    try:
        catalog = Client.open(
            STAC_URL,
            stac_io=StacApiIO(timeout=(10, 30), max_retries=1),
        )
        search = catalog.search(
            collections=[HAND_COLLECTION],
            bbox=list(bounds),
            limit=100,
            max_items=None,
        )
        items = []
        for item in search.items():
            items.append(item)
            if len(items) > MAX_CATALOG_TILES:
                raise TerrainProcessingError(
                    "HAND search exceeds the 256-tile task limit; use a smaller AOI."
                )
    except TerrainProcessingError:
        raise
    except Exception:
        # URLs from upstream exceptions can include signed query parameters.
        raise TerrainProcessingError("Could not search the ASF HAND catalog.") from None

    if not items:
        raise TerrainProcessingError("No HAND tiles intersect the requested AOI.")

    collection = None
    if any(_raster_href(item) is None for item in items):
        try:
            collection = catalog.get_collection(HAND_COLLECTION)
        except Exception:
            # Complete search IDs still permit the documented public fallback.
            pass

    tiles: dict[str, RasterTile] = {}
    for item in sorted(items, key=lambda candidate: candidate.id):
        href = _raster_href(item)
        if href is None and collection is not None:
            try:
                full_item = collection.get_item(item.id)
            except Exception:
                full_item = None
            if full_item is not None:
                href = _raster_href(full_item)
        if href is None:
            href = _public_tile_href(item.id)
        tile = RasterTile(item.id, href, HAND_COLLECTION)
        if item.id in tiles and tiles[item.id].href != href:
            raise TerrainProcessingError("HAND catalog returned conflicting tile assets.")
        tiles[item.id] = tile
    return list(tiles.values())


def analyze_hand_tiles(
    tiles: Iterable[RasterTile],
    bbox: Sequence[float],
    *,
    output_path: str | Path | None = None,
    max_pixels: int = 10_000_000,
) -> dict:
    """Analyze local or discovered tiles without another catalog request."""
    with rasterio.Env(
        AWS_NO_SIGN_REQUEST="YES",
        AWS_REGION="us-west-2",
        GDAL_DISABLE_READDIR_ON_OPEN="TRUE",
        GDAL_HTTP_TIMEOUT=30,
        GDAL_HTTP_CONNECTTIMEOUT=10,
        GDAL_HTTP_MAX_RETRY=2,
    ):
        result = analyze_raster_tiles(
            tiles,
            bbox,
            kind="hand",
            output_path=output_path,
            max_pixels=max_pixels,
        )
    result["source"] = "ASF GLO-30 HAND"
    result["collection"] = HAND_COLLECTION
    result["limitations"].append(
        "HAND provides drainage-relative terrain context; it does not detect floodwater."
    )
    return result


def analyze_hand(
    bbox: Sequence[float],
    *,
    output_path: str | Path | None = None,
) -> dict:
    """Discover all matching ASF tiles and calculate AOI terrain statistics."""
    tiles = discover_hand_tiles(bbox)
    return analyze_hand_tiles(tiles, bbox, output_path=output_path)
