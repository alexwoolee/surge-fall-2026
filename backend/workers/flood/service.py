"""Combine approved Sentinel-1, DEM and HAND evidence for one bounded AOI.

Discovery belongs to callers. Each independent processor is attempted, and a
failed component contributes an error rather than invented measurements. This
wrapper combines AOI summaries, without resampling or inferring flood depth.
"""

from collections.abc import Iterable
import json
import math
from numbers import Real
from typing import Any
from uuid import uuid4

from backend.workers.flood._raster import RasterTile, _safe_href, validate_bbox
from backend.workers.flood.hand import HAND_COLLECTION, MAX_CATALOG_TILES, analyze_hand_tiles
from backend.workers.flood.sentinel1 import (
    SENTINEL1_COLLECTION, Sentinel1Scene, _iso, _validate_scene,
    analyze_sentinel1_scene,
)
from backend.workers.flood.terrain import DEM_COLLECTION, MAX_TILES, analyze_dem_tiles


FLOOD_WORKER_ID = "flood-worker"
FLOOD_ANALYSIS_TYPE = "surface_water_and_terrain"
_NAMES = {"sentinel1": "Sentinel-1 RTC", "dem": "Copernicus DEM GLO-30", "hand": "ASF GLO-30 HAND"}
_GLOBAL_LIMITATIONS = [
    "Candidate surface water is not confirmed flooding; permanent water and other low-backscatter surfaces can be candidates.",
    "All components use the same requested AOI, but their native grids, valid coverage and acquisition or product dates differ.",
    "This worker combines AOI summaries without a spatial water/terrain overlay, reprojection or resampling; "
    "it does not calculate water depth, flood extent change, severity or causation.",
    "Processing status describes component success; coverage is reported separately and missing cells are not extrapolated.",
    "This is environmental analysis evidence, not an emergency-response or evacuation determination.",
]


class FloodWorkerError(Exception):
    """Raised for invalid task inputs before any component processing begins."""


def _tiles(resources: Iterable[RasterTile], collection: str, maximum: int) -> list[RasterTile]:
    """Bound consumption even for generators, then validate and deduplicate."""
    try:
        unique = {}
        for index, tile in enumerate(resources):
            if index >= maximum:
                raise ValueError
            if (
                not isinstance(tile, RasterTile)
                or not isinstance(tile.tile_id, str) or not tile.tile_id.strip()
                or not isinstance(tile.href, str) or not tile.href.strip()
                or tile.collection != collection
            ):
                raise ValueError
            if tile.tile_id in unique and unique[tile.tile_id] != tile:
                raise ValueError
            # Reject malformed URLs up front without exposing provider tokens.
            _safe_href(tile.href)
            unique[tile.tile_id] = tile
        if not unique:
            raise ValueError
        return [unique[key] for key in sorted(unique)]
    except Exception:
        raise FloodWorkerError(
            f"{collection} requires 1 to {maximum} valid RasterTile resources from its approved collection, "
            "with no conflicting tile IDs."
        ) from None


def _number(value, *, minimum=None, maximum=None) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError
    value = float(value)
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ValueError
    return value


def _integer(value, *, minimum=0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError
    return value


def _same_number(value, expected) -> None:
    if not math.isclose(_number(value), expected, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError


def _coverage(result: dict) -> dict:
    coverage = result["coverage"]
    aoi = _integer(coverage["aoi_pixels"], minimum=1)
    covered = _integer(coverage["covered_pixels"], minimum=1)
    valid = _integer(coverage["valid_pixels"], minimum=1)
    if not valid <= covered <= aoi:
        raise ValueError
    _number(coverage["coverage_fraction"], minimum=0, maximum=1)
    _number(coverage["valid_fraction"], minimum=0, maximum=1)
    _same_number(coverage["coverage_fraction"], covered / aoi)
    _same_number(coverage["valid_fraction"], valid / aoi)
    if coverage["status"] != ("complete" if valid == aoi else "partial"):
        raise ValueError
    return coverage


def _statistics(statistics: dict, count: int, units: str) -> dict:
    if statistics["units"] != units or _integer(statistics["count"], minimum=1) != count:
        raise ValueError
    values = {key: _number(statistics[key]) for key in ("min", "max", "mean", "median")}
    if values["min"] > values["max"] or not all(
        (values[key] >= values["min"] or math.isclose(values[key], values["min"], rel_tol=1e-12, abs_tol=1e-12))
        and (values[key] <= values["max"] or math.isclose(values[key], values["max"], rel_tol=1e-12, abs_tol=1e-12))
        for key in ("mean", "median")
    ):
        raise ValueError
    return values


def _checked_result(component: str, result, bbox, inputs, threshold_db: float, max_pixels: int):
    """Check the fields used in assembly before accepting a component success.

    The JSON round trip also detaches processor-owned containers and rejects
    NaN, infinity and non-serializable values anywhere in the full evidence.
    Shared application contracts remain the next phase's responsibility.
    """
    result = json.loads(json.dumps(result, allow_nan=False))
    if not isinstance(result, dict) or validate_bbox(result["bbox"]) != bbox:
        raise ValueError
    if result["source"] != _NAMES[component]:
        raise ValueError
    limitations = result["limitations"]
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(note, str) or not note.strip() for note in limitations
    ):
        raise ValueError
    coverage = _coverage(result)
    raster = result["raster"]
    grid_cells = _integer(raster["width"], minimum=1) * _integer(raster["height"], minimum=1)
    if not coverage["aoi_pixels"] <= grid_cells <= max_pixels:
        raise ValueError
    if not isinstance(raster["crs"], str) or not raster["crs"]:
        raise ValueError
    source = {"component": component, "name": result["source"], "collection": result["collection"]}
    if component == "sentinel1":
        scene = result["scene"]
        if (
            result["collection"] != SENTINEL1_COLLECTION
            or scene["scene_id"] != inputs.scene_id
            or _iso(scene["acquired_at"]) != _iso(inputs.acquired_at)
            or scene["polarization"] != inputs.polarization
            or scene["orbit_state"] != inputs.orbit_state
            or scene["relative_orbit"] != inputs.relative_orbit
            or validate_bbox(scene["bbox"]) != validate_bbox(inputs.bbox)
            or not isinstance(scene["href"], str)
            or _safe_href(scene["href"]) != _safe_href(inputs.href)
        ):
            raise ValueError
        scene["href"] = _safe_href(scene["href"])
        scene["acquired_at"] = _iso(scene["acquired_at"])
        _same_number(result["method"]["threshold_db"], threshold_db)
        _statistics(result["backscatter_db"], coverage["valid_pixels"], "dB")
        candidate = result["candidate_water"]
        candidate_count = _integer(candidate["count"])
        if candidate_count > coverage["valid_pixels"]:
            raise ValueError
        _number(candidate["fraction_valid"], minimum=0, maximum=1)
        _number(candidate["area_km2"], minimum=0)
        _same_number(candidate["fraction_valid"], candidate_count / coverage["valid_pixels"])
        area = _number(raster["pixel_area_m2"], minimum=0)
        if area == 0:
            raise ValueError
        _same_number(candidate["area_km2"], candidate_count * area / 1_000_000)
        summary = {
            "candidate_area_km2": float(candidate["area_km2"]),
            "candidate_fraction_valid": float(candidate["fraction_valid"]),
            "valid_fraction": float(coverage["valid_fraction"]),
            "scene_id": scene["scene_id"], "acquired_at": scene["acquired_at"],
            "threshold_db": threshold_db,
        }
        source.update(resources_used=[scene["href"]], scene_id=scene["scene_id"],
                      acquired_at=scene["acquired_at"], polarization=scene["polarization"])
    else:
        collection = DEM_COLLECTION if component == "dem" else HAND_COLLECTION
        if result["kind"] != component or result["collection"] != collection:
            raise ValueError
        statistics = _statistics(result["statistics"], coverage["valid_pixels"], "m")
        if component == "hand" and statistics["min"] < 0:
            raise ValueError
        expected = {tile.tile_id: tile for tile in inputs}
        tiles = result["source_tiles"]
        if not isinstance(tiles, list) or len(tiles) != len(expected):
            raise ValueError
        seen = set()
        contributed = 0
        for tile in tiles:
            identifier = tile["tile_id"]
            original = expected[identifier]
            if (identifier in seen or tile["collection"] != collection
                    or not isinstance(tile["href"], str)
                    or _safe_href(tile["href"]) != _safe_href(original.href)):
                raise ValueError
            tile["href"] = _safe_href(tile["href"])
            seen.add(identifier)
            intersection = _integer(tile["intersecting_pixels"])
            valid = _integer(tile["valid_pixels"])
            contribution = _integer(tile["contributed_pixels"])
            if not contribution <= valid <= intersection <= coverage["aoi_pixels"]:
                raise ValueError
            contributed += contribution
        if contributed != coverage["valid_pixels"]:
            raise ValueError
        summary = {
            "mean_m": statistics["mean"], "min_m": statistics["min"],
            "max_m": statistics["max"], "median_m": statistics["median"],
            "valid_pixels": coverage["valid_pixels"],
            "valid_fraction": float(coverage["valid_fraction"]), "tile_count": len(tiles),
        }
        source["resources_used"] = [tile["href"] for tile in tiles]
    return result, summary, source


def run_flood_analysis(
    scene: Sentinel1Scene,
    dem_tiles: Iterable[RasterTile],
    hand_tiles: Iterable[RasterTile],
    bbox,
    *,
    task_id: str | None = None,
    threshold_db: float = -17.0,
    terrain_max_pixels: int = 10_000_000,
    sentinel_max_pixels: int = 20_000_000,
) -> dict[str, Any]:
    """Run three independent processors and return complete/partial/failed evidence.

    Invalid task metadata raises ``FloodWorkerError`` before work starts.
    Source access, processing and malformed-output failures are component errors;
    other components still run. ``complete`` means all processors succeeded,
    including when one of them reports partial valid-data coverage.
    """
    try:
        if task_id is not None and (
            not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128
        ):
            raise ValueError
        bounds = validate_bbox(bbox)
        threshold_db = _number(threshold_db, minimum=-40, maximum=0)
        _integer(terrain_max_pixels, minimum=1)
        _integer(sentinel_max_pixels, minimum=1)
        _validate_scene(scene)
        _safe_href(scene.href)
    except Exception:
        raise FloodWorkerError(
            "Invalid Flood worker task: require a valid WGS84 bbox, calibrated VV scene, "
            "a finite threshold from -40 to 0 dB, positive integer pixel limits, "
            "and an optional nonempty task_id of at most 128 characters."
        ) from None
    normalized_dem = _tiles(dem_tiles, DEM_COLLECTION, MAX_TILES)
    normalized_hand = _tiles(hand_tiles, HAND_COLLECTION, MAX_CATALOG_TILES)
    result = {
        "task_id": str(uuid4()) if task_id is None else task_id,
        "worker_id": FLOOD_WORKER_ID, "analysis_type": FLOOD_ANALYSIS_TYPE,
        "status": "failed", "bbox": dict(zip(("west", "south", "east", "north"), bounds)),
        "summary": {}, "evidence": {}, "sources": [], "coverage": {},
        "errors": [], "limitations": [],
    }
    components = (
        ("sentinel1", "surface_water", analyze_sentinel1_scene, scene,
         {"threshold_db": threshold_db, "max_pixels": sentinel_max_pixels}),
        ("dem", "elevation", analyze_dem_tiles, normalized_dem, {"max_pixels": terrain_max_pixels}),
        ("hand", "hand", analyze_hand_tiles, normalized_hand, {"max_pixels": terrain_max_pixels}),
    )
    for component, summary_key, processor, inputs, options in components:
        try:
            processed = processor(inputs, bounds, **options)
        except Exception:
            result["errors"].append({
                "component": component, "code": "processing_failed",
                "message": f"{_NAMES[component]} processing failed; check source access and raster metadata.",
            })
            continue
        try:
            evidence, summary, source = _checked_result(
                component, processed, bounds, inputs, threshold_db, options["max_pixels"],
            )
        except Exception:
            result["errors"].append({
                "component": component, "code": "invalid_result",
                "message": f"{_NAMES[component]} processor returned invalid structured evidence.",
            })
            continue
        result["evidence"][component] = evidence
        result["coverage"][component] = evidence["coverage"].copy()
        result["summary"][summary_key] = summary
        result["sources"].append(source)
        result["limitations"].extend(evidence["limitations"])
    successes = len(result["evidence"])
    result["status"] = "complete" if successes == 3 else "partial" if successes else "failed"
    result["limitations"].extend(_GLOBAL_LIMITATIONS)
    if result["errors"]:
        result["limitations"].append(
            "One or more components failed; absent evidence and summary fields represent unavailable results, not zero measurements."
        )
    result["limitations"] = list(dict.fromkeys(result["limitations"]))
    # Final serialization is an invariant of the public service boundary.
    json.dumps(result, allow_nan=False)
    return result
