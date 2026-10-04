"""Bounded, deterministic AOI statistics for aligned DEM and HAND tiles.

No raster is resampled. AOI membership is determined by pixel centers in
WGS84; edge cells are not weighted by the fraction of their area in the AOI.
Rasterio's windowed read API keeps source reads bounded to the requested AOI:
https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html
"""

from contextlib import ExitStack
from dataclasses import dataclass
import math
import nturl2path
from numbers import Real
import os
from pathlib import Path
import sys
from typing import Iterable, Literal
from urllib.parse import unquote, urlsplit, urlunsplit

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import transform as transform_coordinates, transform_bounds
from rasterio.windows import Window, from_bounds


class TerrainProcessingError(Exception):
    """Raised when terrain evidence cannot be calculated safely."""


@dataclass(frozen=True)
class RasterTile:
    tile_id: str
    href: str
    collection: str = ""


def validate_bbox(bbox) -> tuple[float, float, float, float]:
    """Validate a non-wrapping WGS84 (west, south, east, north) rectangle."""
    try:
        values = tuple(bbox)
    except TypeError:
        raise TerrainProcessingError("bbox must contain four finite coordinates.") from None
    if len(values) != 4 or any(
        not isinstance(value, Real) or isinstance(value, bool)
        or not math.isfinite(value) for value in values
    ):
        raise TerrainProcessingError("bbox must contain four finite coordinates.")
    west, south, east, north = map(float, values)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise TerrainProcessingError(
            "Invalid WGS84 bbox: require -180 <= west < east <= 180 and "
            "-90 <= south < north <= 90; antimeridian wrapping is unsupported."
        )
    return west, south, east, north


def _safe_href(href: str) -> str:
    """Keep source provenance without signed query strings or URL credentials."""
    parsed = urlsplit(str(href))
    if parsed.scheme:
        netloc = parsed.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    return str(href)


def _file_uri_path(href: str, *, windows: bool) -> str:
    """Decode a file URI once using the target platform's path conventions.

    In particular, ``/C:/...`` is URI syntax, not a Windows drive-rooted path.
    Windows non-local authorities identify UNC shares; they have no portable
    local mapping on POSIX. Ambiguous URI suffixes fail closed for write guards.
    """
    try:
        parsed = urlsplit(href)
        if (parsed.scheme != "file" or "?" in href or "#" in href
                or any(character in href for character in "\r\n\t")):
            raise ValueError
        authority = parsed.netloc
        if authority.lower() == "localhost":
            authority = ""
        if authority and (not windows or any(character in authority for character in "@:%\\")):
            raise ValueError
        if windows:
            # nturl2path is the Windows implementation of urllib.request's
            # url2pathname and is also available for regression tests on POSIX.
            value = ("//" + authority if authority else "") + parsed.path
            decoded = nturl2path.url2pathname(value)
        else:
            decoded = unquote(parsed.path, encoding=sys.getfilesystemencoding(),
                              errors=sys.getfilesystemencodeerrors())
        if not decoded or "\x00" in decoded:
            raise ValueError
        return decoded
    except (ValueError, OSError):
        raise TerrainProcessingError(
            "File URI cannot be mapped safely to a local path on this platform."
        ) from None


def _local_path(href: str) -> Path | None:
    """Recognize native paths and file URIs for source-overwrite protection."""
    href = str(href)
    if href.lower().startswith("file:"):
        return Path(_file_uri_path(href, windows=os.name == "nt"))
    # Do not URL-decode ordinary filenames, including literal percent signs.
    # A drive path may contain two slashes without becoming a remote URI.
    if "://" not in href or (len(href) >= 2 and href[0].isascii() and href[0].isalpha() and href[1] == ":"):
        return Path(href)
    return None if urlsplit(href).scheme else Path(href)


def _grid_offset(value: float) -> int:
    nearest = round(value)
    if not math.isclose(value, nearest, rel_tol=0, abs_tol=1e-6):
        raise TerrainProcessingError("Terrain tiles have incompatible grid alignment.")
    return nearest


def _validate_source(source, reference=None) -> None:
    if source.crs is None:
        raise TerrainProcessingError("Terrain raster has no declared CRS.")
    if source.count != 1:
        raise TerrainProcessingError("Terrain raster must have exactly one band.")
    if np.dtype(source.dtypes[0]).kind not in "iuf":
        raise TerrainProcessingError("Terrain raster must contain real numerical values.")
    grid = source.transform
    if not all(math.isfinite(value) for value in tuple(grid)[:6]):
        raise TerrainProcessingError("Terrain raster has a nonfinite transform.")
    if grid.b != 0 or grid.d != 0 or grid.a <= 0 or grid.e >= 0:
        raise TerrainProcessingError("Terrain raster must have a north-up, unrotated grid.")
    unit = source.units[0]
    if unit and unit.lower().strip() not in {"m", "meter", "meters", "metre", "metres"}:
        raise TerrainProcessingError("Terrain raster band units must be meters.")
    if not all(math.isfinite(value) for value in (source.scales[0], source.offsets[0])):
        raise TerrainProcessingError("Terrain raster scale and offset must be finite.")
    if reference is None:
        return
    if source.crs != reference.crs:
        raise TerrainProcessingError("Terrain tiles have mixed CRS; reprojection is required.")
    if not all(math.isclose(a, b, rel_tol=1e-10, abs_tol=0) for a, b in (
        (grid.a, reference.transform.a), (grid.e, reference.transform.e)
    )):
        raise TerrainProcessingError("Terrain tiles have incompatible grid resolutions.")
    _grid_offset((grid.c - reference.transform.c) / grid.a)
    _grid_offset((grid.f - reference.transform.f) / grid.e)


def _aoi_mask(shape, grid, crs, bbox) -> np.ndarray:
    """Check original WGS84 bounds at pixel centers, including projected grids.

    Transforming centers back to WGS84 avoids approximating curved projected
    AOI edges with four corners. Chunking bounds temporary coordinate arrays.
    Eight coordinate-magnitude ULPs account for floating arithmetic at an
    inclusive bbox edge; this tolerance does not depend on pixel size.
    """
    height, width = shape
    west, south, east, north = bbox
    longitude_tolerance = 8 * np.spacing(max(1.0, abs(west), abs(east)))
    latitude_tolerance = 8 * np.spacing(max(1.0, abs(south), abs(north)))
    west, east = west - longitude_tolerance, east + longitude_tolerance
    south, north = south - latitude_tolerance, north + latitude_tolerance
    columns = grid.c + (np.arange(width) + 0.5) * grid.a
    rows = grid.f + (np.arange(height) + 0.5) * grid.e
    if crs == CRS.from_epsg(4326):
        return ((rows >= south) & (rows <= north))[:, None] & (
            (columns >= west) & (columns <= east)
        )[None, :]
    mask = np.zeros(shape, dtype=bool)
    chunk_rows = max(1, min(128, 100_000 // width))
    for start in range(0, height, chunk_rows):
        stop = min(height, start + chunk_rows)
        x, y = np.meshgrid(columns, rows[start:stop])
        lon, lat = transform_coordinates(crs, "EPSG:4326", x.ravel(), y.ravel())
        lon, lat = np.asarray(lon), np.asarray(lat)
        mask[start:stop] = (
            np.isfinite(lon) & np.isfinite(lat)
            & (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
        ).reshape(stop - start, width)
    return mask


def analyze_raster_tiles(
    tiles: Iterable[RasterTile],
    bbox,
    *,
    kind: Literal["dem", "hand"] = "dem",
    output_path: str | Path | None = None,
    max_pixels: int = 10_000_000,
) -> dict:
    """Combine all source tiles and return meter statistics for valid AOI cells.

    Sources must share a CRS, resolution, and integer-aligned north-up grid.
    Overlaps use the first *valid* pixel in stable tile-ID order; later tiles
    can fill earlier nodata. Missing tile coverage is explicitly reported.
    The pixel limit applies to the AOI bounding rectangle before allocation.
    """
    bbox = validate_bbox(bbox)
    if kind not in {"dem", "hand"}:
        raise TerrainProcessingError("kind must be 'dem' or 'hand'.")
    if isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels <= 0:
        raise TerrainProcessingError("max_pixels must be a positive integer.")
    try:
        tile_list = list(tiles)
    except TypeError:
        raise TerrainProcessingError("tiles must be an iterable of RasterTile objects.") from None
    if not tile_list:
        raise TerrainProcessingError("No terrain tiles were supplied.")
    if any(not isinstance(tile, RasterTile) or not tile.tile_id or not tile.href for tile in tile_list):
        raise TerrainProcessingError("Every terrain tile requires a tile_id and href.")
    unique = {}
    for tile in tile_list:
        if tile.tile_id in unique and unique[tile.tile_id] != tile:
            raise TerrainProcessingError("Conflicting sources have the same terrain tile ID.")
        unique[tile.tile_id] = tile
    ordered = sorted(unique.values(), key=lambda tile: tile.tile_id)
    if output_path is not None:
        output_path = Path(output_path)
        if any((local := _local_path(tile.href)) is not None
               and local.resolve() == output_path.resolve() for tile in ordered):
            raise TerrainProcessingError("Output artifact must not overwrite a source tile.")
    try:
        return _analyze(ordered, bbox, kind, output_path, max_pixels)
    except TerrainProcessingError:
        raise
    except Exception:
        # GDAL error strings may include signed source URLs. Keep those out of
        # public exceptions and result payloads, including chained exceptions.
        raise TerrainProcessingError(
            "Terrain raster access or processing failed; check source access and raster metadata."
        ) from None


def _analyze(tiles, bbox, kind, output_path, max_pixels) -> dict:
    with ExitStack() as stack:
        sources = [stack.enter_context(rasterio.open(tile.href)) for tile in tiles]
        reference = sources[0]
        for source in sources:
            _validate_source(source, reference)
        # Densification bounds curved AOI edges in projected coordinate systems.
        bounds = transform_bounds("EPSG:4326", reference.crs, *bbox, densify_pts=128)
        if not all(math.isfinite(value) for value in bounds):
            raise TerrainProcessingError("AOI cannot be transformed into the raster CRS.")
        floating = from_bounds(*bounds, transform=reference.transform)
        col0, row0 = math.floor(floating.col_off + 1e-7), math.floor(floating.row_off + 1e-7)
        col1 = math.ceil(floating.col_off + floating.width - 1e-7)
        row1 = math.ceil(floating.row_off + floating.height - 1e-7)
        width, height = col1 - col0, row1 - row0
        if width <= 0 or height <= 0:
            raise TerrainProcessingError("AOI contains no raster pixel centers.")
        if width * height > max_pixels:
            raise TerrainProcessingError(
                f"AOI requires {width * height} grid cells, exceeding max_pixels={max_pixels}."
            )
        grid = reference.transform * Affine.translation(col0, row0)
        shape = (height, width)
        aoi = _aoi_mask(shape, grid, reference.crs, bbox)
        aoi_pixels = int(aoi.sum())
        if aoi_pixels == 0:
            raise TerrainProcessingError("AOI contains no raster pixel centers.")
        values = np.full(shape, np.nan, dtype=np.float64)
        covered = np.zeros(shape, dtype=bool)
        provenance = []
        for tile, source in zip(tiles, sources):
            source_col = _grid_offset((source.transform.c - grid.c) / grid.a)
            source_row = _grid_offset((source.transform.f - grid.f) / grid.e)
            dest_col0, dest_row0 = max(0, source_col), max(0, source_row)
            dest_col1 = min(width, source_col + source.width)
            dest_row1 = min(height, source_row + source.height)
            entry = {
                "tile_id": tile.tile_id, "href": _safe_href(tile.href),
                "collection": tile.collection, "intersecting_pixels": 0,
                "valid_pixels": 0, "contributed_pixels": 0,
                "nodata_declared": source.nodata is not None,
            }
            provenance.append(entry)
            if dest_col1 <= dest_col0 or dest_row1 <= dest_row0:
                continue
            region = (slice(dest_row0, dest_row1), slice(dest_col0, dest_col1))
            selected = aoi[region]
            entry["intersecting_pixels"] = int(selected.sum())
            if not entry["intersecting_pixels"]:
                continue
            window = Window(
                dest_col0 - source_col, dest_row0 - source_row,
                dest_col1 - dest_col0, dest_row1 - dest_row0,
            )
            pixels = source.read(1, window=window, masked=True)
            raw = np.asarray(pixels.data, dtype=np.float64)
            valid = selected & ~np.ma.getmaskarray(pixels) & np.isfinite(raw)
            # An explicit mask can override GDAL's nodata mask. Honor both.
            if source.nodata is not None:
                valid &= raw != source.nodata
            with np.errstate(invalid="ignore", over="ignore"):
                raw = raw * source.scales[0] + source.offsets[0]
            valid &= np.isfinite(raw)
            if kind == "hand":
                valid &= raw >= 0
            covered[region] |= selected
            target = values[region]
            contribute = valid & ~np.isfinite(target)
            target[contribute] = raw[contribute]
            entry["valid_pixels"] = int(valid.sum())
            entry["contributed_pixels"] = int(contribute.sum())
        valid_values = values[np.isfinite(values)]
        count = int(valid_values.size)
        if count == 0:
            raise TerrainProcessingError("No valid terrain pixels intersect the requested AOI.")
        covered_pixels = int(covered.sum())
        limitations = [
            "AOI clipping includes pixel centers within the WGS84 bbox; boundary cells "
            "are not fractionally area-weighted. Inclusive edges allow eight "
            "coordinate-magnitude ULPs for floating-point roundoff.",
            "Statistics weight each valid source-grid pixel equally; geographic-grid "
            "pixels do not have equal ground area.",
            "Overlapping tiles use the first valid pixel in sorted tile-ID order; "
            "no reprojection or resampling is performed.",
        ]
        if any(not source.units[0] for source in sources):
            limitations.append("Bands without declared units are interpreted in meters for DEM/HAND products.")
        if kind == "hand":
            limitations.append("HAND describes height above drainage and is supporting terrain evidence, not a flood detector.")
            if any(not entry["nodata_declared"] for entry in provenance):
                limitations.append(
                    "Some HAND tiles declare no nodata value. Masks, nonfinite and negative "
                    "values are excluded; zero is valid. Undeclared positive sentinel values "
                    "cannot be identified reliably."
                )
        if covered_pixels < aoi_pixels:
            limitations.append("Source tiles do not cover all AOI grid cells; statistics describe the available subset.")
        if count < covered_pixels:
            limitations.append("Some covered AOI cells are nodata or invalid; statistics exclude those cells.")
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(
                output_path, "w", driver="GTiff", width=width, height=height,
                count=1, dtype="float64", crs=reference.crs, transform=grid,
                nodata=np.nan, compress="deflate",
            ) as destination:
                destination.write(values, 1)
                destination.set_band_unit(1, "m")
                destination.update_tags(terrain_kind=kind, clipping="pixel_centers")
        return {
            "kind": kind, "bbox": list(bbox),
            "statistics": {
                "units": "m", "min": float(valid_values.min()),
                "max": float(valid_values.max()), "mean": float(valid_values.mean()),
                "median": float(np.median(valid_values)), "count": count,
            },
            "coverage": {
                "aoi_pixels": aoi_pixels, "covered_pixels": covered_pixels,
                "valid_pixels": count, "coverage_fraction": covered_pixels / aoi_pixels,
                "valid_fraction": count / aoi_pixels,
                "status": "complete" if count == aoi_pixels else "partial",
            },
            "raster": {
                "crs": reference.crs.to_string(), "resolution": [grid.a, -grid.e],
                "width": width, "height": height, "transform": list(grid)[:6],
                "clipping": "pixel_centers",
            },
            "source_tiles": provenance, "limitations": limitations,
            "artifact_path": str(output_path.resolve()) if output_path else None,
        }
