"""Independent scene and static terrain context for a bounded location/date."""

from datetime import datetime, timedelta, timezone

from backend.shared.context_contracts import (
    ContextComponent, ContextTask, HeightMetrics, WaterMetrics, context_result, unavailable,
)
from backend.shared.status import TaskState
from backend.workers.flood.hand import analyze_hand_tiles, discover_hand_tiles, HAND_COLLECTION, MAX_CATALOG_TILES
from backend.workers.flood.terrain import analyze_dem_tiles, discover_dem_tiles, DEM_COLLECTION, MAX_TILES
from backend.workers.flood.sentinel1 import analyze_sentinel1_scene, discover_sentinel1_scene, _timestamp, _validate_scene
from backend.workers.flood.service import _checked_result, _tiles


# Launch is a conservative lower bound; later empty provider coverage remains unavailable.
SENTINEL1_START = datetime(2014, 4, 3, tzinfo=timezone.utc)


def _water(task):
    if task.end_time <= SENTINEL1_START:
        return unavailable("sentinel1", "before_product_coverage")
    try:
        scene = discover_sentinel1_scene(task.bbox.as_tuple(), task.start_time,
                                         task.end_time - timedelta(microseconds=1),
                                         reference_time=task.end_time - timedelta(microseconds=1))
    except Exception:
        return unavailable("sentinel1", "source_unavailable")
    try:
        _validate_scene(scene)
        acquired = _timestamp(scene.acquired_at)
        if not task.start_time <= acquired < task.end_time:
            raise ValueError
    except Exception:
        return unavailable("sentinel1", "invalid_result")
    try:
        raw = analyze_sentinel1_scene(scene, task.bbox.as_tuple(), threshold_db=-17.0, max_pixels=20_000_000)
    except Exception:
        return unavailable("sentinel1", "processing_failed")
    try:
        _, summary, _ = _checked_result("sentinel1", raw, task.bbox.as_tuple(), scene, -17.0, 20_000_000)
        metrics = WaterMetrics(**{key: summary[key] for key in ("candidate_fraction_valid", "candidate_area_km2", "valid_fraction", "threshold_db")})
        return ContextComponent(component="sentinel1", availability="available", reason="measured",
                                temporal_kind="observation", observed_start=acquired, observed_end=acquired, metrics=metrics)
    except Exception:
        return unavailable("sentinel1", "invalid_result")


def _terrain(task, component):
    discover, analyze, collection, maximum = (
        (discover_dem_tiles, analyze_dem_tiles, DEM_COLLECTION, MAX_TILES) if component == "dem"
        else (discover_hand_tiles, analyze_hand_tiles, HAND_COLLECTION, MAX_CATALOG_TILES)
    )
    try:
        tiles = _tiles(discover(task.bbox.as_tuple()), collection, maximum)
    except Exception:
        return unavailable(component, "source_unavailable")
    try:
        raw = analyze(tiles, task.bbox.as_tuple(), max_pixels=10_000_000)
    except Exception:
        return unavailable(component, "processing_failed")
    try:
        _, summary, _ = _checked_result(component, raw, task.bbox.as_tuple(), tiles, -17.0, 10_000_000)
        return ContextComponent(component=component, availability="available", reason="static_noncontemporaneous",
                                temporal_kind="static_context", metrics=HeightMetrics(**summary))
    except Exception:
        return unavailable(component, "invalid_result")


def run_flood_context(task: ContextTask, progress) -> dict:
    task = ContextTask.model_validate(task.model_dump(mode="json"))
    if task.analysis_type != "surface_water_and_terrain":
        raise ValueError("Environmental context task does not match the Flood role.")
    progress(TaskState.PROCESSING)
    # Discovery and processing are independent: absent satellite coverage cannot
    # suppress DEM/HAND results, and a DEM provider failure cannot suppress HAND.
    components = [_water(task), _terrain(task, "dem"), _terrain(task, "hand")]
    progress(TaskState.PREPARING_RESULT)
    return context_result(task, components)
