"""Deterministic candidate-water evidence from calibrated Sentinel-1 RTC.

Planetary Computer's ``sentinel-1-rtc`` VV assets contain linear gamma0
power, unlike the raw digital numbers in ``sentinel-1-grd``. Conversion is
10 * log10(power); a configurable low-backscatter threshold is a screening
method, not a flood classification or probability estimate.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
from numbers import Real
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import numpy as np
import planetary_computer as pc
from pystac_client import Client
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds

from backend.workers.flood._raster import (
    TerrainProcessingError, _aoi_mask, _local_path, _safe_href, validate_bbox,
)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SENTINEL1_COLLECTION = "sentinel-1-rtc"
MAX_SCENES = 128
SELECTION_POLICY = (
    "Largest intersection of scene metadata bbox with requested AOI bbox, "
    "then acquisition nearest reference time, then ascending scene ID. "
    "Metadata bboxes are coverage proxies; actual valid coverage is measured from pixels."
)


class Sentinel1ProcessingError(Exception):
    """Raised when calibrated SAR evidence cannot be calculated safely."""


@dataclass(frozen=True)
class Sentinel1Scene:
    scene_id: str
    href: str
    acquired_at: str | datetime
    bbox: tuple[float, float, float, float]
    collection: str = SENTINEL1_COLLECTION
    polarization: str = "VV"
    orbit_state: str | None = None
    relative_orbit: int | None = None


def _bbox(value):
    try:
        return validate_bbox(value)
    except TerrainProcessingError as exc:
        raise Sentinel1ProcessingError(str(exc)) from None


def _timestamp(value, label="timestamp") -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise Sentinel1ProcessingError(f"{label} must be an ISO timestamp with a timezone.") from None


def _iso(value) -> str:
    return _timestamp(value).isoformat().replace("+00:00", "Z")


def _validate_scene(scene) -> None:
    if not isinstance(scene, Sentinel1Scene):
        raise Sentinel1ProcessingError("Every scene must be a Sentinel1Scene object.")
    if not isinstance(scene.scene_id, str) or not scene.scene_id.strip():
        raise Sentinel1ProcessingError("Scene requires a nonempty scene_id.")
    if not isinstance(scene.href, str) or not scene.href.strip():
        raise Sentinel1ProcessingError("Scene requires a nonempty raster href.")
    if scene.collection != SENTINEL1_COLLECTION:
        raise Sentinel1ProcessingError("Only calibrated sentinel-1-rtc assets are supported; raw GRD is unsupported.")
    if scene.polarization != "VV":
        raise Sentinel1ProcessingError("Candidate-water processing requires VV polarization.")
    if scene.orbit_state not in {None, "ascending", "descending"}:
        raise Sentinel1ProcessingError("Scene orbit_state must be ascending or descending when supplied.")
    if scene.relative_orbit is not None and (
        isinstance(scene.relative_orbit, bool) or not isinstance(scene.relative_orbit, int)
        or not 1 <= scene.relative_orbit <= 175
    ):
        raise Sentinel1ProcessingError("Scene relative_orbit must be an integer from 1 to 175.")
    _bbox(scene.bbox)
    _timestamp(scene.acquired_at, "acquired_at")


def select_scene(scenes: Iterable[Sentinel1Scene], bbox, reference_time) -> Sentinel1Scene:
    """Rank all eligible scenes deterministically, using bbox coverage as a proxy."""
    bbox = _bbox(bbox)
    reference = _timestamp(reference_time, "reference_time")
    try:
        supplied = list(scenes)
    except TypeError:
        raise Sentinel1ProcessingError("scenes must be an iterable of Sentinel1Scene objects.") from None
    unique = {}
    ranked = []
    for scene in supplied:
        _validate_scene(scene)
        if scene.scene_id in unique and unique[scene.scene_id] != scene:
            raise Sentinel1ProcessingError("Conflicting sources have the same Sentinel-1 scene ID.")
        unique[scene.scene_id] = scene
    west, south, east, north = bbox
    aoi_area = (east - west) * (north - south)
    for scene in unique.values():
        sw, ss, se, sn = _bbox(scene.bbox)
        overlap = max(0.0, min(east, se) - max(west, sw)) * max(0.0, min(north, sn) - max(south, ss))
        if overlap:
            distance = abs((_timestamp(scene.acquired_at) - reference).total_seconds())
            ranked.append((-overlap / aoi_area, distance, scene.scene_id, scene))
    if not ranked:
        raise Sentinel1ProcessingError("No supported Sentinel-1 VV scene intersects the requested AOI.")
    return min(ranked, key=lambda item: item[:3])[3]


def discover_sentinel1_scene(bbox, start_time, end_time, *, reference_time=None) -> Sentinel1Scene:
    """Read every matching STAC page, select one calibrated VV asset, then sign it."""
    bbox = _bbox(bbox)
    start = _timestamp(start_time, "start_time")
    end = _timestamp(end_time, "end_time")
    if start > end:
        raise Sentinel1ProcessingError("start_time must not be after end_time.")
    reference = _timestamp(reference_time, "reference_time") if reference_time is not None else start + (end - start) / 2
    try:
        catalog = Client.open(STAC_URL, timeout=30)
        items = catalog.search(
            collections=[SENTINEL1_COLLECTION], bbox=bbox,
            datetime=f"{_iso(start)}/{_iso(end)}", limit=100,
        ).items()
        scenes = []
        for index, item in enumerate(items, start=1):
            if index > MAX_SCENES:
                raise Sentinel1ProcessingError("Sentinel-1 request exceeds 128 scenes; narrow the date range or AOI.")
            if item.collection_id != SENTINEL1_COLLECTION:
                raise Sentinel1ProcessingError("Provider returned an unsupported Sentinel-1 collection.")
            polarizations = item.properties.get("sar:polarizations")
            if not isinstance(polarizations, (list, tuple)) or "VV" not in polarizations:
                continue
            asset = item.assets.get("vv")
            if asset is None or not asset.href:
                raise Sentinel1ProcessingError("Sentinel-1 VV metadata has no corresponding raster asset.")
            acquired = _timestamp(item.datetime, "acquired_at")
            if not start <= acquired <= end:
                raise Sentinel1ProcessingError("Provider returned a Sentinel-1 scene outside the requested time range.")
            scenes.append(Sentinel1Scene(
                scene_id=item.id, href=asset.href, acquired_at=_iso(acquired),
                bbox=tuple(item.bbox), collection=item.collection_id,
                polarization="VV", orbit_state=item.properties.get("sat:orbit_state"),
                relative_orbit=item.properties.get("sat:relative_orbit"),
            ))
        selected = select_scene(scenes, bbox, reference)
        parsed = urlsplit(selected.href)
        if parsed.scheme == "https" and (parsed.hostname or "").endswith(".blob.core.windows.net"):
            selected = replace(selected, href=pc.sign(selected.href))
        return selected
    except Sentinel1ProcessingError:
        raise
    except Exception:
        raise Sentinel1ProcessingError("Sentinel-1 discovery or asset signing failed; check provider access and scene metadata.") from None


def _validate_raster(source) -> None:
    epsg = source.crs.to_epsg() if source.crs else None
    if epsg is None or not (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760):
        raise Sentinel1ProcessingError("Sentinel-1 RTC raster must use a supported WGS84 UTM CRS in meters.")
    if source.count != 1 or np.dtype(source.dtypes[0]).kind != "f":
        raise Sentinel1ProcessingError("Sentinel-1 RTC requires one floating-point linear gamma0 band; integer GRD is unsupported.")
    grid = source.transform
    if not all(math.isfinite(v) for v in tuple(grid)[:6]):
        raise Sentinel1ProcessingError("Sentinel-1 RTC raster has a nonfinite transform.")
    if grid.b != 0 or grid.d != 0 or grid.a <= 0 or grid.e >= 0:
        raise Sentinel1ProcessingError("Sentinel-1 RTC raster must have a north-up, unrotated grid.")
    if source.scales[0] != 1 or source.offsets[0] != 0:
        raise Sentinel1ProcessingError("Sentinel-1 RTC linear gamma0 requires identity scale and offset.")
    unit = source.units[0]
    if unit and unit.lower().strip() in {"db", "decibel", "decibels"}:
        raise Sentinel1ProcessingError("Sentinel-1 RTC input must be linear gamma0 power, not dB.")


def analyze_sentinel1_scene(
    scene: Sentinel1Scene, bbox, *, threshold_db: float = -17.0,
    output_dir: str | Path | None = None, max_pixels: int = 20_000_000,
) -> dict:
    """Clip native RTC cells and screen low VV backscatter as candidate water."""
    _validate_scene(scene)
    bbox = _bbox(bbox)
    if isinstance(threshold_db, bool) or not isinstance(threshold_db, Real) or not math.isfinite(threshold_db) or not -40 <= threshold_db <= 0:
        raise Sentinel1ProcessingError("threshold_db must be a finite number from -40 to 0 dB.")
    if isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels <= 0:
        raise Sentinel1ProcessingError("max_pixels must be a positive integer.")
    try:
        output = Path(output_dir) if output_dir is not None else None
        if output is not None:
            local = _local_path(scene.href)
            if local is not None and any(
                local.resolve() == (output / name).resolve()
                for name in ("backscatter_db.tif", "candidate_water.tif")
            ):
                raise Sentinel1ProcessingError("Output artifact must not overwrite the source raster.")
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="TRUE", GDAL_HTTP_TIMEOUT="30",
            GDAL_HTTP_CONNECTTIMEOUT="10", GDAL_HTTP_MAX_RETRY="2",
        ):
            return _analyze(scene, bbox, float(threshold_db), output, max_pixels)
    except Sentinel1ProcessingError:
        raise
    except Exception:
        # GDAL/provider errors may contain signed URLs. Do not propagate them.
        raise Sentinel1ProcessingError("Sentinel-1 raster access or processing failed; check source access and raster metadata.") from None


def _analyze(scene, bbox, threshold_db, output, max_pixels):
    with rasterio.open(scene.href) as source:
        _validate_raster(source)
        bounds = transform_bounds("EPSG:4326", source.crs, *bbox, densify_pts=128)
        if not all(math.isfinite(value) for value in bounds):
            raise Sentinel1ProcessingError("AOI cannot be transformed into the Sentinel-1 raster CRS.")
        floating = from_bounds(*bounds, transform=source.transform)
        col0, row0 = math.floor(floating.col_off + 1e-7), math.floor(floating.row_off + 1e-7)
        col1 = math.ceil(floating.col_off + floating.width - 1e-7)
        row1 = math.ceil(floating.row_off + floating.height - 1e-7)
        width, height = col1 - col0, row1 - row0
        if width <= 0 or height <= 0:
            raise Sentinel1ProcessingError("AOI contains no raster pixel centers.")
        if width * height > max_pixels:
            raise Sentinel1ProcessingError(f"AOI requires {width * height} grid cells, exceeding max_pixels={max_pixels}.")
        grid = source.transform * Affine.translation(col0, row0)
        shape = (height, width)
        aoi = _aoi_mask(shape, grid, source.crs, bbox)
        aoi_pixels = int(aoi.sum())
        if not aoi_pixels:
            raise Sentinel1ProcessingError("AOI contains no raster pixel centers.")
        backscatter = np.full(shape, np.nan, dtype=np.float64)
        read_col0, read_row0 = max(0, col0), max(0, row0)
        read_col1, read_row1 = min(source.width, col1), min(source.height, row1)
        covered_pixels = 0
        if read_col0 < read_col1 and read_row0 < read_row1:
            region = (
                slice(read_row0 - row0, read_row1 - row0),
                slice(read_col0 - col0, read_col1 - col0),
            )
            selected = aoi[region]
            covered_pixels = int(selected.sum())
            window = Window(read_col0, read_row0, read_col1 - read_col0, read_row1 - read_row0)
            pixels = source.read(1, window=window, masked=True)
            power = np.asarray(pixels.data, dtype=np.float64)
            valid = selected & ~np.ma.getmaskarray(pixels) & np.isfinite(power) & (power > 0)
            # Explicit raster masks can override GDAL's nodata mask; honor both.
            if source.nodata is not None:
                valid &= power != source.nodata
            backscatter[region][valid] = 10 * np.log10(power[valid])
        valid = np.isfinite(backscatter)
        values = backscatter[valid]
        count = int(values.size)
        if not count:
            raise Sentinel1ProcessingError("No valid positive Sentinel-1 gamma0 pixels intersect the requested AOI.")
        pixel_area_m2 = abs(grid.a * grid.e)

        def candidate_summary(threshold):
            candidates = int(np.count_nonzero(values <= threshold))
            return {"count": candidates, "fraction_valid": candidates / count,
                    "area_km2": candidates * pixel_area_m2 / 1_000_000}

        candidate = candidate_summary(threshold_db)
        sensitivity = [
            {"threshold_db": threshold, **candidate_summary(threshold)}
            for threshold in (threshold_db - 2, threshold_db, threshold_db + 2)
        ]
        limitations = [
            "Low VV backscatter is candidate surface-water evidence, not confirmed floodwater; "
            "permanent water, radar shadow and smooth non-water surfaces can also be dark.",
            "A fixed threshold is an explainable screening assumption, not a locally calibrated classifier. "
            "The +/-2 dB sensitivity range describes parameter dependence, not confidence or probability.",
            "Wind-roughened water, vegetation and urban double-bounce can hide water; speckle can create isolated candidates.",
            "The provider supplies radiometrically terrain-corrected gamma0. MeshMind applies no additional "
            "speckle, thermal-noise or border-noise filtering, terrain-shadow masking, or resampling.",
            "A single acquisition cannot separate new inundation from permanent water or establish event evolution.",
            "Selection uses metadata bbox overlap as a coverage proxy, not the scene footprint or valid-data coverage.",
            "AOI membership uses pixel centers with eight coordinate-magnitude ULPs of boundary tolerance. "
            "Boundary cells are not fractionally area-weighted.",
            "Area is approximate UTM planimetric area, calculated from native pixel spacing; "
            "grid spacing is not the independent sensor resolution.",
        ]
        if count < aoi_pixels:
            limitations.append("The scene has partial valid AOI coverage; reported fractions use valid pixels and do not extrapolate into missing cells.")
        artifacts = None
        if output is not None:
            output.mkdir(parents=True, exist_ok=True)
            common = dict(driver="GTiff", width=width, height=height, count=1,
                          crs=source.crs, transform=grid, compress="deflate")
            db_path = output / "backscatter_db.tif"
            mask_path = output / "candidate_water.tif"
            with rasterio.open(db_path, "w", dtype="float64", nodata=np.nan, **common) as destination:
                destination.write(backscatter, 1)
                destination.set_band_unit(1, "dB")
                destination.update_tags(scene_id=scene.scene_id, polarization="VV", measurement="gamma0", clipping="pixel_centers")
            water = np.full(shape, 255, dtype=np.uint8)
            water[valid] = (backscatter[valid] <= threshold_db).astype(np.uint8)
            with rasterio.open(mask_path, "w", dtype="uint8", nodata=255, **common) as destination:
                destination.write(water, 1)
                destination.update_tags(scene_id=scene.scene_id, threshold_db=str(threshold_db),
                                        classes="0=noncandidate,1=candidate_water,255=invalid", clipping="pixel_centers")
            artifacts = {"backscatter_db": str(db_path.resolve()), "candidate_water": str(mask_path.resolve())}
        return {
            "source": "Sentinel-1 RTC", "collection": scene.collection, "bbox": list(bbox),
            "scene": {
                "scene_id": scene.scene_id, "acquired_at": _iso(scene.acquired_at),
                "polarization": scene.polarization, "orbit_state": scene.orbit_state,
                "relative_orbit": scene.relative_orbit, "href": _safe_href(scene.href),
                "bbox": list(_bbox(scene.bbox)),
            },
            "method": {
                "input": "linear gamma0 power", "conversion": "10 * log10(gamma0)",
                "threshold_db": threshold_db, "comparison": "<=", "smoothing": "none added by MeshMind",
                "clipping": "pixel_centers", "area_method": "UTM planimetric pixel area",
                "selection": SELECTION_POLICY,
            },
            "coverage": {
                "aoi_pixels": aoi_pixels, "covered_pixels": covered_pixels, "valid_pixels": count,
                "coverage_fraction": covered_pixels / aoi_pixels, "valid_fraction": count / aoi_pixels,
                "status": "complete" if count == aoi_pixels else "partial",
            },
            "raster": {
                "crs": source.crs.to_string(), "resolution": [grid.a, -grid.e],
                "width": width, "height": height, "transform": list(grid)[:6],
                "pixel_area_m2": pixel_area_m2,
            },
            "backscatter_db": {
                "units": "dB", "min": float(values.min()), "max": float(values.max()),
                "mean": float(values.mean()), "median": float(np.median(values)), "count": count,
            },
            "candidate_water": candidate, "sensitivity": sensitivity,
            "limitations": limitations, "artifacts": artifacts,
        }
